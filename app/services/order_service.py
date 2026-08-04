import secrets
import string
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Category, ModifierGroup, Order, OrderItem, OrderItemExclusion, MenuItem, OrderStatus, FulfillmentMethod, OrderItemModifier, ModifierOption, Driver, WalletTransaction, TransactionType, Restaurant

class OrderService:
    @staticmethod
    async def generate_delivery_pin(db: AsyncSession) -> str:
        """Generate a globally unique 6-digit numeric PIN."""
        characters = string.digits
        while True:
            pin = ''.join(secrets.choice(characters) for _ in range(6))
            res = await db.execute(select(Order).where(Order.delivery_pin == pin))
            if not res.scalar_one_or_none():
                return pin

    @staticmethod
    async def process_flow_submission(db: AsyncSession, wa_id: str, restaurant_id: int, flow_data: dict):
        """
        Takes the data from the WhatsApp Flow and turns it into a real Order
        with individual OrderItems in the database.
        """
        total_price = 0.0

        selected_items = flow_data.get("selected_items")
        if not isinstance(selected_items, list) or not selected_items:
            raise ValueError("Order payload must include at least one selected item.")

        # 1. Determine if it's Delivery or Pickup
        method_str = flow_data.get("method", "delivery")
        method = (
            FulfillmentMethod.DELIVERY
            if method_str == "delivery"
            else FulfillmentMethod.PICKUP
        )

        # 2. Create the Main Order record
        new_order = Order(
            restaurant_id=restaurant_id,
            customer_wa_id=wa_id,
            fulfillment_method=method,
            status=OrderStatus.PENDING,  # Waiting for location/confirmation
            total_price=0.0,
        )
        db.add(new_order)
        await db.flush()  # This gives us the Order ID to link items to

        valid_item_count = 0

        # 3. Process each item selected in the Flow
        for selection in selected_items:
            try:
                item_id = int(selection["id"])
            except (TypeError, ValueError, KeyError):
                raise ValueError("Each selected item must include a valid numeric id.")

            qty = int(selection.get("qty", 1) or 1)
            if qty < 1:
                raise ValueError("Item quantity must be at least 1.")

            # Fetch the item from DB to get the official price (prevents price hacking)
            res = await db.execute(
                select(MenuItem)
                .join(Category)
                .where(MenuItem.id == item_id, Category.restaurant_id == restaurant_id)
            )
            item = res.scalar_one_or_none()

            if not item or not item.is_available:
                raise ValueError(f"Menu item {item_id} is not available.")

            valid_item_count += 1
            subtotal = item.price * qty
            total_price += subtotal

            # Create the specific OrderItem
            order_line = OrderItem(
                order_id=new_order.id,
                menu_item_id=item.id,
                quantity=qty,
                unit_price=item.price,
            )
            db.add(order_line)
            await db.flush()  # Get the order_line.id

            # Handle exclusions
            exclusions = selection.get("exclusions", [])
            for exc in exclusions:
                exclusion = OrderItemExclusion(
                    order_item_id=order_line.id,
                    ingredient_name=exc
                )
                db.add(exclusion)

            # Handle modifiers
            modifiers = selection.get("modifiers", [])
            for mod_id in modifiers:
                # Add price of modifier and ensure it belongs to this restaurant
                mod_res = await db.execute(
                    select(ModifierOption)
                    .join(ModifierOption.group)
                    .join(ModifierGroup.menu_item)
                    .join(MenuItem.category)
                    .where(ModifierOption.id == mod_id, Category.restaurant_id == restaurant_id)
                )
                mod_option = mod_res.scalar_one_or_none()
                if not mod_option:
                    raise ValueError(f"Modifier option {mod_id} is invalid for this restaurant.")

                order_line.unit_price += mod_option.price_override
                total_price += (mod_option.price_override * qty)
                mod_entry = OrderItemModifier(
                    order_item_id=order_line.id,
                    modifier_option_id=mod_id
                )
                db.add(mod_entry)

        if valid_item_count == 0:
            raise ValueError("At least one available item must be selected.")

        # 4. Update the final total price, deduct wallet balance, and save
        new_order.total_price = total_price
        
        # Deduct 3.0 MAD from Prepaid Wallet
        res_rest = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
        restaurant = res_rest.scalar_one_or_none()
        if restaurant:
            if restaurant.wallet_balance <= -75.0:
                raise ValueError("ERROR_SCREEN")
            restaurant.wallet_balance -= 3.0
            transaction = WalletTransaction(
                restaurant_id=restaurant_id,
                amount=-3.0,
                type=TransactionType.DEBIT,
                description=f"Order commission (Order #{new_order.id})"
            )
            db.add(transaction)
            
        await db.commit()
        return new_order

    @staticmethod
    async def notify_customer_background(
        restaurant_token: str,
        restaurant_phone_id: str,
        customer_wa_id: str,
        customer_lang: str,
        order_id: int,
        status: str,
        delivery_pin: str = None
    ):
        """
        Background task to send WhatsApp status updates without slowing down the dashboard API.
        We initialize a specific WhatsAppService instance per restaurant.
        """
        from app.services.whatsapp import WhatsAppService
        from app.core.database import AsyncSessionLocal
        from sqlalchemy.future import select
        from sqlalchemy.orm import selectinload

        async with AsyncSessionLocal() as db:
            res = await db.execute(select(Order).where(Order.id == order_id).options(
                selectinload(Order.items).selectinload(OrderItem.menu_item)
            ))
            order = res.scalar_one_or_none()
            if not order: return

            summary = None
            if status == "accepted" and order.items:
                summary = "📋 *Order Summary:*\n" + "\n".join([f"- {item.quantity}x {item.menu_item.name_en}" for item in order.items if item.menu_item])
                
            ws = WhatsAppService(token=restaurant_token, phone_id=restaurant_phone_id)
            await ws.send_order_status_notification(
                to_phone=customer_wa_id,
                lang=customer_lang,
                tracking_code=order.tracking_code,
                status=status,
                delivery_pin=delivery_pin,
                order_summary=summary
            )

    @staticmethod
    async def notify_driver_dispatch_background(
        restaurant_token: str,
        restaurant_phone_id: str,
        driver_wa_id: str,
        order_id: int,
        latitude: float,
        longitude: float
    ):
        """Send Direct Assignment Card to a specific driver."""
        from app.services.whatsapp import WhatsAppService
        ws = WhatsAppService(token=restaurant_token, phone_id=restaurant_phone_id)
        await ws.send_driver_dispatch_card(
            to_phone=driver_wa_id,
            order_id=order_id,
            latitude=latitude,
            longitude=longitude
        )

    @staticmethod
    async def notify_drivers_broadcast_background(
        db: AsyncSession, # Note: using DB in background task can be tricky if session is closed. Better to pass list of wa_ids or let the method create a new session
        restaurant_token: str,
        restaurant_phone_id: str,
        restaurant_id: int,
        order_id: int
    ):
        """Send Broadcast Card to all active drivers."""
        from app.services.whatsapp import WhatsAppService
        from app.core.database import AsyncSessionLocal
        
        ws = WhatsAppService(token=restaurant_token, phone_id=restaurant_phone_id)
        
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(Driver).where(Driver.restaurant_id == restaurant_id, Driver.is_active)
            )
            drivers = res.scalars().all()
            
            for driver in drivers:
                await ws.send_driver_broadcast_card(
                    to_phone=driver.wa_id,
                    order_id=order_id
                )