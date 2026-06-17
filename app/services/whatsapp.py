import httpx
import logging
from app.core.config import settings
from datetime import datetime

logger = logging.getLogger(__name__)

class WhatsAppService:
    def __init__(self, token: str = None, phone_id: str = None):
        self.token = token or settings.WHATSAPP_API_TOKEN
        self.phone_id = phone_id or settings.PHONE_NUMBER_ID
        self.url = f"https://graph.facebook.com/v21.0/{self.phone_id}/messages"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    async def _post(self, payload: dict):
        """Central send helper with error logging."""
        async with httpx.AsyncClient() as client:
            response = await client.post(self.url, headers=self.headers, json=payload)
            if response.status_code not in (200, 201):
                logger.error(
                    "WhatsApp API error %s: %s", response.status_code, response.text
                )
            return response

    async def send_text_message(self, to_phone: str, text: str):
        await self._post(
            {
                "messaging_product": "whatsapp",
                "to": to_phone,
                "type": "text",
                "text": {"body": text},
            }
        )

    async def send_language_picker(self, to_phone: str):
        await self._post(
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to_phone,
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "header": {"type": "text", "text": "Bienvenue / Marhba / Welcome"},
                    "body": {"text": "Choisissez votre langue / اختر اللغة"},
                    "action": {
                        "button": "Languages",
                        "sections": [
                            {
                                "title": "Select",
                                "rows": [
                                    {"id": "lang_fr", "title": "Français"},
                                    {"id": "lang_ar", "title": "العربية (Darija)"},
                                    {"id": "lang_en", "title": "English"},
                                ],
                            }
                        ],
                    },
                },
            }
        )

    async def send_welcome_button(self, to_phone: str, msg: str, btn: str):
        await self._post(
            {
                "messaging_product": "whatsapp",
                "to": to_phone,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": msg},
                    "action": {
                        "buttons": [
                            {
                                "type": "reply",
                                "reply": {"id": "btn_view_menu", "title": btn},
                            }
                        ]
                    },
                },
            }
        )

    async def send_main_menu_flow(self, to_phone: str, lang: str, restaurant_id: int = 1):
        """
        Launches the Single-Flow Commerce Experience.
        Token format: session_{wa_id}_{restaurant_id}_{timestamp}
        """
        flow_token = f"session_{to_phone}_{restaurant_id}_{int(datetime.utcnow().timestamp())}"

        await self._post(
            {
                "messaging_product": "whatsapp",
                "to": to_phone,
                "type": "interactive",
                "interactive": {
                    "type": "flow",
                    "header": {"type": "text", "text": "GEQO Menu"},
                    "body": {"text": "Tap below to open the menu app"},
                    "action": {
                        "name": "flow",
                        "parameters": {
                            "flow_message_version": "3",
                            "flow_token": flow_token,
                            "flow_id": settings.WHATSAPP_FLOW_ID,
                            "flow_cta": "Open Menu",
                            "flow_action": "navigate",
                            "flow_action_payload": {"screen": "CATEGORIES_SCREEN"},
                        },
                    },
                },
            }
        )

    async def request_location(self, to_phone: str, lang: str, total: float):
        text_map = {
            "fr": f"Total: {total} MAD. S'il vous plaît, envoyez votre localisation 📍",
            "ar": f"المجموع: {total} درهم. من فضلك أرسل موقعك 📍",
            "en": f"Total: {total} MAD. Please share your location 📍",
        }
        text = text_map.get(lang, text_map["fr"])

        await self._post(
            {
                "messaging_product": "whatsapp",
                "to": to_phone,
                "type": "interactive",
                "interactive": {
                    "type": "location_request_message",
                    "body": {"text": text},
                    "action": {"name": "send_location"},
                },
            }
        )

    async def send_order_confirmation(self, to_phone: str, lang: str):
        text_map = {
            "fr": "🛵 Merci ! Votre commande est confirmée. On arrive !",
            "ar": "🛵 شكراً! طلبك مؤكد. في الطريق إليك!",
            "en": "🛵 Thank you! Your order is confirmed. We're on our way!",
        }
        await self.send_text_message(to_phone, text_map.get(lang, text_map["fr"]))

    async def send_cart_summary(self, to_phone: str, lang: str, cart_items: list, total: str):
        summary_dict = {
            "fr": f"Votre panier:\n" + "\n".join([f"- {item['quantity']}x {item['name']} ({item['subtotal']})" for item in cart_items]) + f"\n\nTotal: {total}",
            "ar": f"سلتك:\n" + "\n".join([f"- {item['quantity']}x {item['name']} ({item['subtotal']})" for item in cart_items]) + f"\n\nالمجموع: {total}",
            "en": f"Your cart:\n" + "\n".join([f"- {item['quantity']}x {item['name']} ({item['subtotal']})" for item in cart_items]) + f"\n\nTotal: {total}",
        }
        summary_text = summary_dict.get(lang, summary_dict["fr"])

        await self._post(
            {
                "messaging_product": "whatsapp",
                "to": to_phone,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": summary_text},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": "confirm_order", "title": {"fr": "Confirmer", "ar": "تأكيد", "en": "Confirm"}.get(lang, "Confirm")}},
                            {"type": "reply", "reply": {"id": "change_order", "title": {"fr": "Modifier", "ar": "تغيير", "en": "Change"}.get(lang, "Change")}},
                        ]
                    },
                },
            }
        )

    async def send_order_status_notification(self, to_phone: str, lang: str, order_id: int, status: str, delivery_pin: str = None):
        """Sends translated status updates to the customer"""
        status_messages = {
            "accepted": {
                "fr": f"✅ Votre commande #{order_id} a été acceptée et est en cours de préparation !",
                "ar": f"✅ تم قبول طلبك رقم {order_id} وجاري تحضيره!",
                "en": f"✅ Your order #{order_id} has been accepted and is being prepared!"
            },
            "preparing": {
                "fr": f"🍳 Le chef a commencé à préparer votre commande #{order_id} !",
                "ar": f"🍳 بدأ الشيف في تحضير طلبك رقم {order_id}!",
                "en": f"🍳 The chef has started preparing your order #{order_id}!"
            },
            "ready": {
                "fr": f"🛍️ Bonne nouvelle ! Votre commande #{order_id} est prête pour la récupération.",
                "ar": f"🛍️ خبر سار! طلبك رقم {order_id} جاهز.",
                "en": f"🛍️ Good news! Your order #{order_id} is ready."
            },
            "dispatched": {
                "fr": f"🛵 Votre commande #{order_id} est en route ! Notre livreur vous contactera.",
                "ar": f"🛵 طلبك رقم {order_id} في الطريق إليك! سيتصل بك المندوب قريبًا.",
                "en": f"🛵 Your order #{order_id} is on the way! Our driver will contact you."
            },
            "delivered": {
                "fr": f"🍽️ Votre commande #{order_id} a été livrée. Bon appétit !",
                "ar": f"🍽️ تم توصيل طلبك رقم {order_id}. بالصحة والراحة!",
                "en": f"🍽️ Your order #{order_id} has been delivered. Enjoy your meal!"
            },
            "cancelled": {
                "fr": f"❌ Désolé, votre commande #{order_id} a été annulée. Veuillez contacter le restaurant.",
                "ar": f"❌ عذراً، تم إلغاء طلبك رقم {order_id}. يرجى التواصل مع المطعم.",
                "en": f"❌ We're sorry, your order #{order_id} was cancelled. Please contact the restaurant."
            }
        }

        # If it's a status we don't notify for (like 'pending' or 'received'), exit safely
        if status not in status_messages:
            return

        # Default to French if customer language is missing
        customer_lang = lang if lang in ["fr", "ar", "en"] else "fr"
        text = status_messages[status][customer_lang]
        
        if delivery_pin and status in ["accepted", "dispatched"]:
            pin_text = f"\n\n🔑 Votre code PIN de livraison / رمز التوصيل الخاص بك / Your delivery PIN is: *{delivery_pin}*\nGardez-le pour confirmer la livraison. / احتفظ به لتأكيد التوصيل. / Keep it to confirm delivery."
            text += pin_text
        
        await self.send_text_message(to_phone, text)

    async def notify_manager_new_order(self, manager_wa_id: str, order_id: int, total: float, method: str):
        """Sends a notification to the restaurant manager with Accept/Reject buttons."""
        text = f"🚨 *New Order Received!*\n\n*Order ID:* #{order_id}\n*Type:* {method.capitalize()}\n*Total:* {total} MAD\n\nWhat would you like to do?"
        
        await self._post(
            {
                "messaging_product": "whatsapp",
                "to": manager_wa_id,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": text},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": f"mgr_accept_{order_id}", "title": "Accept"}},
                            {"type": "reply", "reply": {"id": f"mgr_reject_{order_id}", "title": "Reject"}},
                        ]
                    },
                },
            }
        )

    async def send_driver_dispatch_card(self, to_phone: str, order_id: int, latitude: float, longitude: float):
        """Sends a card to the driver with location and a button to confirm delivery (opens flow)."""
        flow_token = f"driver_{order_id}_{to_phone}"
        loc_str = f"Lat: {latitude}, Lng: {longitude}"
        await self._post(
            {
                "messaging_product": "whatsapp",
                "to": to_phone,
                "type": "interactive",
                "interactive": {
                    "type": "flow",
                    "header": {"type": "text", "text": f"Delivery Order #{order_id}"},
                    "body": {"text": f"Deliver to: {loc_str}\nTap below when you reach the customer to confirm delivery."},
                    "action": {
                        "name": "flow",
                        "parameters": {
                            "flow_message_version": "3",
                            "flow_token": flow_token,
                            "flow_id": settings.WHATSAPP_FLOW_ID,
                            "flow_cta": "Confirm Delivery",
                            "flow_action": "navigate",
                            "flow_action_payload": {"screen": "CONFIRM_DELIVERY_SCREEN", "data": {"order_id": order_id}},
                        },
                    },
                },
            }
        )

    async def send_driver_broadcast_card(self, to_phone: str, order_id: int):
        """Sends a notification to drivers that an order is available to claim."""
        text = f"🚨 *New Delivery Available!*\n\n*Order ID:* #{order_id}\n\nDo you want to claim this delivery?"
        await self._post(
            {
                "messaging_product": "whatsapp",
                "to": to_phone,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": text},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": f"claim_order_{order_id}", "title": "Claim Order"}},
                        ]
                    },
                },
            }
        )