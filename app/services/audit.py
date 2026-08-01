from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import AuditLog

async def log_audit_action(
    db: AsyncSession,
    actor_user_id: int,
    actor_email: str,
    action: str,
    target: str,
    detail: dict,
    restaurant_id: Optional[int]
):
    """
    Log an audit action. This function adds the AuditLog record to the DB session 
    but does NOT commit it. It relies on the parent transaction to commit.
    """
    log_entry = AuditLog(
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        action=action,
        target=target,
        detail=detail,
        restaurant_id=restaurant_id
    )
    db.add(log_entry)
