import asyncio
from sqlalchemy.future import select
from app.core.database import AsyncSessionLocal, engine
from app.models import Base, Restaurant, Category, MenuItem
from app.core.config import settings

async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # 1. Create the Restaurant (Matching your Meta Phone ID)
        # Check if it already exists to avoid duplicates
        res = await db.execute(select(Restaurant).where(Restaurant.phone_number_id == settings.PHONE_NUMBER_ID))
        restaurant = res.scalar_one_or_none()
        
        if not restaurant:
            restaurant = Restaurant(
                name="GEQO Test Kitchen",
                wa_phone_number="YOUR_TEST_NUMBER", # Placeholder
                phone_number_id=settings.PHONE_NUMBER_ID,
                api_token=settings.WHATSAPP_API_TOKEN,
                owner_wa_id="YOUR_PERSONAL_NUMBER" # For alerts
            )
            db.add(restaurant)
            await db.flush()

            # 2. Add a Category (Trilingual)
            cat = Category(
                restaurant_id=restaurant.id,
                name_en="Burgers",
                name_fr="Burgers",
                name_ar="برغر"
            )
            db.add(cat)
            await db.flush()

            # 3. Add Menu Items (Trilingual)
            item1 = MenuItem(
                category_id=cat.id,
                name_en="Cheese Burger",
                name_fr="Burger au Fromage",
                name_ar="تشيز برغر",
                price=45.0,
                is_available=True
            )
            item2 = MenuItem(
                category_id=cat.id,
                name_en="Crispy Chicken",
                name_fr="Poulet Croustillant",
                name_ar="دجاج مقرمش",
                price=55.0,
                is_available=True
            )

            db.add_all([item1, item2])
            await db.commit()
            print("--- SEEDING COMPLETE ---")
            print(f"Restaurant '{restaurant.name}' is ready with {cat.name_en}")
        else:
            print("Mock data already exists, skipping.")

if __name__ == "__main__":
    asyncio.run(seed())
