from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from typing import Optional
from app.core.database import AsyncSessionLocal
from app.core.auth import get_manager_or_admin, User, UserRole
from app.models import Category, MenuItem, ModifierGroup, ModifierOption
from app.services.audit import log_audit_action

router = APIRouter()

# --- Pydantic Schemas ---

class CategoryCreate(BaseModel):
    name_en: str
    name_ar: str
    name_fr: str
    image_url: Optional[str] = None
    restaurant_id: Optional[int] = None # Admin needs to pass this, Manager doesn't

class MenuItemCreate(BaseModel):
    category_id: int
    name_en: str
    name_ar: str
    name_fr: str
    price: float
    item_details: Optional[str] = None
    image_url: Optional[str] = None
    allows_exclusions: bool = False

class ModifierGroupCreate(BaseModel):
    menu_item_id: Optional[int] = None
    category_id: Optional[int] = None
    name_en: str
    name_ar: str
    name_fr: str
    min_selection: int = 0
    max_selection: int = 1

class ModifierOptionCreate(BaseModel):
    group_id: int
    name_en: str
    name_ar: str
    name_fr: str
    price_override: float = 0.0

# --- Helper ---

async def check_restaurant_access(db: AsyncSession, current_user: User, restaurant_id: int):
    if current_user.role == UserRole.RESTAURANT_OWNER and current_user.restaurant_id != restaurant_id:
        raise HTTPException(status_code=403, detail="Not authorized to edit this menu")

# --- Endpoints ---

@router.get("/{restaurant_id}")
async def get_full_menu(restaurant_id: int, current_user: User = Depends(get_manager_or_admin)):
    async with AsyncSessionLocal() as db:
        await check_restaurant_access(db, current_user, restaurant_id)
        
        # Load categories with their own modifier groups, and items with their modifier groups
        stmt = select(Category).where(Category.restaurant_id == restaurant_id).options(
            selectinload(Category.items).selectinload(MenuItem.modifier_groups).selectinload(ModifierGroup.options),
            selectinload(Category.modifier_groups).selectinload(ModifierGroup.options)
        )
        res = await db.execute(stmt)
        categories = res.scalars().all()
        return categories

@router.post("/categories")
async def create_category(category: CategoryCreate, current_user: User = Depends(get_manager_or_admin)):
    async with AsyncSessionLocal() as db:
        target_res_id = current_user.restaurant_id if current_user.role == UserRole.RESTAURANT_OWNER else category.restaurant_id
        if not target_res_id:
            raise HTTPException(status_code=400, detail="restaurant_id required")
        await check_restaurant_access(db, current_user, target_res_id)
        
        new_cat = Category(
            restaurant_id=target_res_id,
            name_en=category.name_en,
            name_ar=category.name_ar,
            name_fr=category.name_fr,
            image_url=category.image_url
        )
        db.add(new_cat)
        await db.commit()
        await db.refresh(new_cat)
        return new_cat

@router.delete("/categories/{cat_id}")
async def delete_category(cat_id: int, current_user: User = Depends(get_manager_or_admin)):
    async with AsyncSessionLocal() as db:
        stmt = select(Category).where(Category.id == cat_id)
        res = await db.execute(stmt)
        cat = res.scalar_one_or_none()
        if not cat:
            raise HTTPException(status_code=404, detail="Category not found")
        await check_restaurant_access(db, current_user, cat.restaurant_id)
        
        await log_audit_action(
            db=db,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            action="CATEGORY_DELETED",
            target=f"category_id={cat.id}",
            detail={"category_name": cat.name_en},
            restaurant_id=cat.restaurant_id
        )
        
        await db.delete(cat)
        await db.commit()
        return {"status": "deleted"}

@router.post("/items")
async def create_item(item: MenuItemCreate, current_user: User = Depends(get_manager_or_admin)):
    async with AsyncSessionLocal() as db:
        stmt = select(Category).where(Category.id == item.category_id)
        res = await db.execute(stmt)
        cat = res.scalar_one_or_none()
        if not cat:
            raise HTTPException(status_code=404, detail="Category not found")
        await check_restaurant_access(db, current_user, cat.restaurant_id)
        
        new_item = MenuItem(
            category_id=item.category_id,
            name_en=item.name_en,
            name_ar=item.name_ar,
            name_fr=item.name_fr,
            price=item.price,
            item_details=item.item_details,
            image_url=item.image_url,
            allows_exclusions=item.allows_exclusions
        )
        db.add(new_item)
        await db.commit()
        await db.refresh(new_item)
        return new_item

@router.delete("/items/{item_id}")
async def delete_item(item_id: int, current_user: User = Depends(get_manager_or_admin)):
    async with AsyncSessionLocal() as db:
        stmt = select(MenuItem).where(MenuItem.id == item_id).options(selectinload(MenuItem.category))
        res = await db.execute(stmt)
        item = res.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        await check_restaurant_access(db, current_user, item.category.restaurant_id)
        await log_audit_action(
            db=db,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            action="MENU_ITEM_DELETED",
            target=f"item_id={item.id}",
            detail={"item_name": item.name_en, "category_id": item.category_id},
            restaurant_id=item.category.restaurant_id
        )
        
        await db.delete(item)
        await db.commit()
        return {"status": "deleted"}

@router.post("/modifiers/groups")
async def create_modifier_group(group: ModifierGroupCreate, current_user: User = Depends(get_manager_or_admin)):
    if (group.menu_item_id is None) == (group.category_id is None):
        raise HTTPException(status_code=400, detail="Must provide exactly one of menu_item_id or category_id")

    async with AsyncSessionLocal() as db:
        if group.menu_item_id:
            stmt = select(MenuItem).where(MenuItem.id == group.menu_item_id).options(selectinload(MenuItem.category))
            res = await db.execute(stmt)
            parent = res.scalar_one_or_none()
            if not parent:
                raise HTTPException(status_code=404, detail="Item not found")
            await check_restaurant_access(db, current_user, parent.category.restaurant_id)
        else:
            stmt = select(Category).where(Category.id == group.category_id)
            res = await db.execute(stmt)
            parent = res.scalar_one_or_none()
            if not parent:
                raise HTTPException(status_code=404, detail="Category not found")
            await check_restaurant_access(db, current_user, parent.restaurant_id)
        
        new_group = ModifierGroup(
            menu_item_id=group.menu_item_id,
            category_id=group.category_id,
            name_en=group.name_en,
            name_ar=group.name_ar,
            name_fr=group.name_fr,
            min_selection=group.min_selection,
            max_selection=group.max_selection
        )
        db.add(new_group)
        await db.commit()
        await db.refresh(new_group)
        return new_group

@router.post("/modifiers/options")
async def create_modifier_option(option: ModifierOptionCreate, current_user: User = Depends(get_manager_or_admin)):
    async with AsyncSessionLocal() as db:
        stmt = select(ModifierGroup).where(ModifierGroup.id == option.group_id).options(
            selectinload(ModifierGroup.menu_item).selectinload(MenuItem.category),
            selectinload(ModifierGroup.category)
        )
        res = await db.execute(stmt)
        group = res.scalar_one_or_none()
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        
        if group.menu_item:
            res_id = group.menu_item.category.restaurant_id
        else:
            res_id = group.category.restaurant_id
            
        await check_restaurant_access(db, current_user, res_id)
        
        new_opt = ModifierOption(
            group_id=option.group_id,
            name_en=option.name_en,
            name_ar=option.name_ar,
            name_fr=option.name_fr,
            price_override=option.price_override
        )
        db.add(new_opt)
        await db.commit()
        await db.refresh(new_opt)
        return new_opt

@router.delete("/modifiers/groups/{group_id}")
async def delete_modifier_group(group_id: int, current_user: User = Depends(get_manager_or_admin)):
    async with AsyncSessionLocal() as db:
        stmt = select(ModifierGroup).where(ModifierGroup.id == group_id).options(
            selectinload(ModifierGroup.menu_item).selectinload(MenuItem.category),
            selectinload(ModifierGroup.category)
        )
        res = await db.execute(stmt)
        group = res.scalar_one_or_none()
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        
        if group.menu_item:
            res_id = group.menu_item.category.restaurant_id
        else:
            res_id = group.category.restaurant_id
        await check_restaurant_access(db, current_user, res_id)
        
        await db.delete(group)
        await db.commit()
        return {"status": "deleted"}

@router.delete("/modifiers/options/{option_id}")
async def delete_modifier_option(option_id: int, current_user: User = Depends(get_manager_or_admin)):
    async with AsyncSessionLocal() as db:
        stmt = select(ModifierOption).where(ModifierOption.id == option_id).options(
            selectinload(ModifierOption.group).selectinload(ModifierGroup.menu_item).selectinload(MenuItem.category),
            selectinload(ModifierOption.group).selectinload(ModifierGroup.category)
        )
        res = await db.execute(stmt)
        opt = res.scalar_one_or_none()
        if not opt:
            raise HTTPException(status_code=404, detail="Option not found")
            
        group = opt.group
        if group.menu_item:
            res_id = group.menu_item.category.restaurant_id
        else:
            res_id = group.category.restaurant_id
        await check_restaurant_access(db, current_user, res_id)
        
        await db.delete(opt)
        await db.commit()
        return {"status": "deleted"}
