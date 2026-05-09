import asyncio
from sqlalchemy.future import select
from app.core.database import AsyncSessionLocal, engine
from app.models import Base, User, UserRole
from app.core.auth import get_password_hash

async def seed_admin():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # Check if admin user already exists
        result = await db.execute(select(User).where(User.email == "admin@geqo.com"))
        admin_user = result.scalar_one_or_none()

        if not admin_user:
            # Create initial admin user
            admin_user = User(
                email="admin@geqo.com",
                password_hash=get_password_hash("admin123"),
                role=UserRole.ADMIN,
                is_active=True
            )
            db.add(admin_user)
            await db.commit()
            print("✅ Admin user created: admin@geqo.com / admin123")
        else:
            print("ℹ️ Admin user already exists")

if __name__ == "__main__":
    asyncio.run(seed_admin())