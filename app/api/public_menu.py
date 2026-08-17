from fastapi import APIRouter, HTTPException
from sqlalchemy.future import select
from app.core.database import AsyncSessionLocal
from app.models import Restaurant, RestaurantStatus, Category, MenuItem, ModifierGroup
from app.services.hours import is_restaurant_open

router = APIRouter()

@router.get("/menu/{restaurant_identifier}")
async def get_public_menu(restaurant_identifier: str):
    """
    Fetch the public menu for a restaurant.
    Includes categories, items, and modifier groups/options.
    """
    import json
    import redis.asyncio as redis_async
    from app.core.config import settings
    
    cache_key = f"cache:menu:{restaurant_identifier}"
    r = None
    
    if settings.REDIS_URL:
        try:
            r = redis_async.from_url(settings.REDIS_URL, decode_responses=True)
            cached_menu = await r.get(cache_key)
            if cached_menu:
                await r.aclose()
                return json.loads(cached_menu)
        except Exception:
            pass # Fail open, ignore cache errors

    async with AsyncSessionLocal() as db:
        # Check if restaurant exists and is active
        if restaurant_identifier.isdigit():
            res = await db.execute(select(Restaurant).where(Restaurant.id == int(restaurant_identifier)))
        else:
            res = await db.execute(select(Restaurant).where(Restaurant.slug == restaurant_identifier))
            
        restaurant = res.scalar_one_or_none()
        if not restaurant or restaurant.status != RestaurantStatus.ACTIVE:
            raise HTTPException(status_code=404, detail="Restaurant not found or inactive")

        # Fetch categories with their items and modifier groups (both levels)
        from sqlalchemy.orm import selectinload
        cat_query = await db.execute(
            select(Category)
            .where(Category.restaurant_id == restaurant.id)
            .options(
                selectinload(Category.items).selectinload(MenuItem.modifier_groups).selectinload(ModifierGroup.options)
            )
        )
        categories = cat_query.scalars().unique().all()
        
        categories_data = []
        all_items_flat = []
        
        for cat in categories:
            items_data = []
            for item in cat.items:
                
                
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
                    "category_id": str(cat.id),
                    "name_fr": item.name_fr,
                    "name_ar": item.name_ar,
                    "name_en": item.name_en,
                    "price": item.price,
                    "item_details": item.item_details,
                    "image_url": item.image_url,
                    "is_available": item.is_available,
                    "allows_exclusions": item.allows_exclusions,
                    "modifier_groups": item_mod_groups
                })
            
            categories_data.append({
                "id": str(cat.id),
                "name_fr": cat.name_fr,
                "name_ar": cat.name_ar,
                "name_en": cat.name_en,
                "image_url": cat.image_url
            })
            all_items_flat.extend(items_data)

        payload = {
            "restaurant": {
                "id": str(restaurant.id),
                "name": restaurant.name,
                "latitude": restaurant.latitude,
                "longitude": restaurant.longitude,
                "base_delivery_fee": restaurant.base_delivery_fee,
                "per_km_delivery_fee": restaurant.per_km_delivery_fee,
                "max_delivery_radius_km": restaurant.max_delivery_radius_km,
                # is_accepting_orders = raw manual toggle;
                # is_open = computed: manual toggle AND operating hours check
                "is_accepting_orders": restaurant.is_accepting_orders,
                "is_open": is_restaurant_open(restaurant),
            },
            "categories": categories_data,
            "items": all_items_flat
        }
        
        if r:
            try:
                await r.setex(cache_key, 300, json.dumps(payload))
                await r.aclose()
            except Exception:
                pass
                
        return payload
