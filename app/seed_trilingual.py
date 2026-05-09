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
        res = await db.execute(select(Restaurant).where(Restaurant.phone_number_id == settings.PHONE_NUMBER_ID))
        restaurant = res.scalar_one_or_none()

        if not restaurant:
            restaurant = Restaurant(
                name="GEQO Test Kitchen",
                wa_phone_number="YOUR_TEST_NUMBER",
                phone_number_id=settings.PHONE_NUMBER_ID,
                api_token=settings.WHATSAPP_API_TOKEN,
                owner_wa_id="YOUR_PERSONAL_NUMBER"
            )
            db.add(restaurant)
            await db.flush()
        else:
            print(f"Restaurant '{restaurant.name}' already exists, skipping.")

        # 2. Add a Category (Trilingual) — only if none exist for this restaurant
        cat_res = await db.execute(
            select(Category).where(Category.restaurant_id == restaurant.id)
        )
        existing_cat = cat_res.scalar_one_or_none()

        if existing_cat:
            print(f"Categories already exist for '{restaurant.name}', skipping seed.")
            return

        cat = Category(
            restaurant_id=restaurant.id,
            name_en="Burgers",
            name_fr="Burgers",
            name_ar="\u0628\u0631\u063a\u0631"
        )
        db.add(cat)
        await db.flush()

        # 3. Add Menu Items (Trilingual)
        item1 = MenuItem(
            category_id=cat.id,
            name_en="Cheese Burger",
            name_fr="Burger au Fromage",
            name_ar="\u062a\u0634\u064a\u0632 \u0628\u0631\u063a\u0631",
            price=45.0,
            is_available=True
        )
        item2 = MenuItem(
            category_id=cat.id,
            name_en="Crispy Chicken",
            name_fr="Poulet Croustillant",
            name_ar="\u062f\u062c\u0627\u062c \u0645\u0642\u0631\u0645\u0634",
            price=55.0,
            is_available=True
        )

        db.add_all([item1, item2])
        await db.commit()
        print("--- SEEDING COMPLETE ---")
        print(f"Restaurant '{restaurant.name}' is ready with {cat.name_en}")

if __name__ == "__main__":
    asyncio.run(seed())
