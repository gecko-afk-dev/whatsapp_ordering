from fastapi import HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from app.core.database import get_db
from app.core.auth import get_current_kitchen_or_above
from app.models import Restaurant, Driver, UserRole

def require_feature(feature_name: str):
    async def feature_dependency(current_user = Depends(get_current_kitchen_or_above), db: AsyncSession = Depends(get_db)):
        if current_user.role == UserRole.ADMIN:
            return current_user
            
        res = await db.execute(select(Restaurant).where(Restaurant.id == current_user.restaurant_id))
        restaurant = res.scalar_one_or_none()
        if not restaurant:
            raise HTTPException(status_code=404, detail="Restaurant not found")
            
        if not restaurant.has_feature(feature_name):
            raise HTTPException(
                status_code=403, 
                detail=f"Feature '{feature_name}' is locked on your current tier. Please upgrade to Scale or Multi."
            )
        return current_user
    return feature_dependency

async def check_delivery_agent_limit(restaurant: Restaurant, db: AsyncSession):
    res = await db.execute(
        select(func.count(Driver.id))
        .where(Driver.restaurant_id == restaurant.id, Driver.is_active)
    )
    active_count = res.scalar() or 0
    if active_count >= restaurant.max_delivery_agents():
        raise HTTPException(
            status_code=403, 
            detail=f"Your {restaurant.subscription_tier.value} tier allows up to {restaurant.max_delivery_agents()} Delivery Agents."
        )

async def check_kds_limit(restaurant: Restaurant, db: AsyncSession):
    # Implement when KDS connection tracking is available
    pass
