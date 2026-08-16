from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.future import select
from typing import List
from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.core.auth import get_manager_or_admin, get_current_kitchen_or_above, User, UserRole
from app.models import Driver

router = APIRouter()

class DriverCreate(BaseModel):
    name: str
    wa_id: str

class DriverResponse(BaseModel):
    id: int
    name: str
    wa_id: str
    is_active: bool

    class Config:
        from_attributes = True

@router.get("/", response_model=List[DriverResponse])
async def list_drivers(current_user: User = Depends(get_current_kitchen_or_above)):
    """
    Read-only driver list. Available to kitchen_staff and cashier for
    KDS dispatch UI. Write operations (POST/DELETE) remain owner/admin-only.
    """
    if not settings.FEATURE_DRIVERS_ENABLED and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Driver management is currently disabled.")

    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Driver).where(Driver.restaurant_id == current_user.restaurant_id))
        return res.scalars().all()

@router.post("/", response_model=DriverResponse)
async def add_driver(driver: DriverCreate, current_user: User = Depends(get_manager_or_admin)):
    if not settings.FEATURE_DRIVERS_ENABLED and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Driver management is currently disabled.")
    async with AsyncSessionLocal() as db:
        if current_user.role != UserRole.ADMIN:
            from app.models import Restaurant
            from app.core.tier_guards import check_delivery_agent_limit
            res = await db.execute(select(Restaurant).where(Restaurant.id == current_user.restaurant_id))
            restaurant = res.scalar_one_or_none()
            if restaurant:
                await check_delivery_agent_limit(restaurant, db)

        new_driver = Driver(
            restaurant_id=current_user.restaurant_id,
            name=driver.name,
            wa_id=driver.wa_id,
            is_active=True
        )
        db.add(new_driver)
        await db.commit()
        await db.refresh(new_driver)
        return new_driver

@router.delete("/{driver_id}")
async def remove_driver(driver_id: int, current_user: User = Depends(get_manager_or_admin)):
    if not settings.FEATURE_DRIVERS_ENABLED and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Driver management is currently disabled.")
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Driver).where(Driver.id == driver_id, Driver.restaurant_id == current_user.restaurant_id))
        driver = res.scalar_one_or_none()
        if not driver:
            raise HTTPException(status_code=404, detail="Driver not found")
        
        await db.delete(driver)
        await db.commit()
        return {"status": "deleted"}
