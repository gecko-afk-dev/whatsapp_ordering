from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from app.core.database import AsyncSessionLocal
from app.models import Restaurant, RestaurantStatus, Category, MenuItem

router = APIRouter()

@router.get("/menu/{restaurant_id}")
async def get_public_menu(restaurant_id: int):
    """
    Fetch the public menu for a restaurant.
    Includes categories, items, and modifier groups/options.
    """
    async with AsyncSessionLocal() as db:
        # Check if restaurant exists and is active
        res = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
        restaurant = res.scalar_one_or_none()
        if not restaurant or restaurant.status != RestaurantStatus.ACTIVE:
            raise HTTPException(status_code=404, detail="Restaurant not found or inactive")

        # Fetch categories with their items and modifier groups (both levels)
        from sqlalchemy.orm import selectinload
        cat_query = await db.execute(
            select(Category)
            .where(Category.restaurant_id == restaurant_id)
            .options(
                selectinload(Category.items).selectinload(MenuItem.modifier_groups).selectinload(ModifierGroup.options),
                selectinload(Category.modifier_groups).selectinload(ModifierGroup.options)
            )
        )
        categories = cat_query.scalars().unique().all()
        
        categories_data = []
        for cat in categories:
            # Serialize category-level modifier groups
            cat_mod_groups = []
            for group in cat.modifier_groups:
                cat_mod_groups.append({
                    "id": group.id,
                    "name_fr": group.name_fr,
                    "name_ar": group.name_ar,
                    "name_en": group.name_en,
                    "min_selection": group.min_selection,
                    "max_selection": group.max_selection,
                    "options": [
                        {
                            "id": opt.id,
                            "name_fr": opt.name_fr,
                            "name_ar": opt.name_ar,
                            "name_en": opt.name_en,
                            "price_override": opt.price_override
                        } for opt in group.options
                    ]
                })

            items_data = []
            for item in cat.items:
                if not item.is_available:
                    continue
                
                # Serialize item-level modifier groups
                item_mod_groups = []
                for group in item.modifier_groups:
                    item_mod_groups.append({
                        "id": group.id,
                        "name_fr": group.name_fr,
                        "name_ar": group.name_ar,
                        "name_en": group.name_en,
                        "min_selection": group.min_selection,
                        "max_selection": group.max_selection,
                        "options": [
                            {
                                "id": opt.id,
                                "name_fr": opt.name_fr,
                                "name_ar": opt.name_ar,
                                "name_en": opt.name_en,
                                "price_override": opt.price_override
                            } for opt in group.options
                        ]
                    })
                
                items_data.append({
                    "id": item.id,
                    "name_fr": item.name_fr,
                    "name_ar": item.name_ar,
                    "name_en": item.name_en,
                    "price": item.price,
                    "item_details": item.item_details,
                    "allows_exclusions": item.allows_exclusions,
                    "modifier_groups": item_mod_groups
                })
            
            categories_data.append({
                "id": cat.id,
                "name_fr": cat.name_fr,
                "name_ar": cat.name_ar,
                "name_en": cat.name_en,
                "modifier_groups": cat_mod_groups,
                "items": items_data
            })

        return {
            "restaurant": {
                "id": restaurant.id,
                "name": restaurant.name,
                "latitude": restaurant.latitude,
                "longitude": restaurant.longitude,
                "base_delivery_fee": restaurant.base_delivery_fee,
                "per_km_delivery_fee": restaurant.per_km_delivery_fee,
                "max_delivery_radius_km": restaurant.max_delivery_radius_km
            },
            "categories": categories_data
        }
