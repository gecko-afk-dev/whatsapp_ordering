import asyncio
import logging
from string import Template

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    @staticmethod
    def _get_sender_address() -> str:
        if not settings.RESEND_FROM_EMAIL:
            return "contacts@mygeqo.com"

        value = settings.RESEND_FROM_EMAIL.strip()
        if "<" in value and ">" in value:
            return value.split("<", 1)[1].split(">", 1)[0].strip()
        return value

    @staticmethod
    def _get_from_header() -> str:
        if settings.RESEND_FROM_EMAIL:
            return settings.RESEND_FROM_EMAIL.strip()
        return "GEQO <contacts@mygeqo.com>"

    @staticmethod
    def _get_resend_headers() -> dict:
        api_key = (settings.RESEND_API_KEY or "").strip()
        if not api_key:
            raise ValueError("RESEND_API_KEY is not configured")
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    async def _send_email_async(to_email: str, subject: str, text_content: str, html_content: str = None, reply_to: str = None):
        """Send an email through the Resend HTTP API."""
        if not settings.RESEND_API_KEY:
            logger.error("Resend API key is not configured; skipping email delivery")
            return False

        payload = {
            "from": EmailService._get_from_header(),
            "to": [to_email],
            "subject": subject,
            "text": text_content,
            "html": html_content or text_content,
        }
        if reply_to:
            payload["reply_to"] = [reply_to]

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "https://api.resend.com/emails",
                    json=payload,
                    headers=EmailService._get_resend_headers(),
                )
                response.raise_for_status()

            logger.info("Successfully sent email to %s via Resend", to_email)
            return True
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text if exc.response else str(exc)
            logger.error("Resend rejected email to %s: %s", to_email, detail)
            return False
        except Exception as exc:
            logger.error("Failed to send email to %s via Resend: %s", to_email, exc)
            return False

    @staticmethod
    async def _send_email_with_retries(to_email: str, subject: str, text_content: str, html_content: str = None, retries: int = 3, delay_seconds: float = 1.0, reply_to: str = None):
        """Retry transient email failures a few times before giving up."""
        last_error = None
        for attempt in range(retries):
            try:
                return await EmailService._send_email_async(to_email, subject, text_content, html_content, reply_to=reply_to)
            except Exception as exc:
                last_error = exc
                if attempt == retries - 1:
                    logger.error("Email send failed after %s attempts for %s: %s", retries, to_email, exc)
                    return False
                logger.warning("Email send attempt %s/%s failed for %s: %s", attempt + 1, retries, to_email, exc)
                await asyncio.sleep(delay_seconds)

        if last_error is not None:
            logger.error("Email send failed for %s: %s", to_email, last_error)
        return False

    @staticmethod
    async def send_beta_confirmation(email: str, manager_name: str, restaurant_name: str, locale: str = "fr"):
        """Sends branded confirmation email for beta signup."""
        try:
            with open("app/templates/email/beta_confirmation.html", "r") as f:
                html_template = f.read()
        except FileNotFoundError:
            logger.warning("Beta confirmation template not found, using basic HTML.")
            html_template = "<h1>Welcome to the Pilot, $manager_name!</h1><p>$restaurant_name is registered.</p>"

        subjects = {
            "en": "Welcome to the GEQO Pilot!",
            "fr": "Bienvenue dans le pilote GEQO !",
            "ar": "مرحباً بك في البرنامج التجريبي لـ GEQO!",
        }
        subject = subjects.get(locale, subjects["fr"])

        translations = {
            "en": {
                "greeting": f"Hello <strong>{manager_name}</strong>,",
                "body_1": f"Congratulations! Your restaurant <strong>{restaurant_name}</strong> is successfully registered for our Casablanca pilot phase.",
                "next_steps_title": "Next Steps:",
                "step_1": "Our team will contact you within 24 hours.",
                "step_2": "Onboarding call and configuration.",
                "step_3": "Launch of your WhatsApp ordering channel.",
                "sign_off": "The GEQO Team",
                "rights_reserved": "All rights reserved.",
            },
            "fr": {
                "greeting": f"Bonjour <strong>{manager_name}</strong>,",
                "body_1": f"Félicitations ! Votre restaurant <strong>{restaurant_name}</strong> est bien enregistré pour participer à notre phase pilote à Casablanca.",
                "next_steps_title": "Prochaines étapes :",
                "step_1": "Notre équipe vous contactera sous 24h.",
                "step_2": "Appel d'intégration et configuration.",
                "step_3": "Lancement de votre canal de commande WhatsApp.",
                "sign_off": "L'équipe GEQO",
                "rights_reserved": "Tous droits réservés.",
            },
            "ar": {
                "greeting": f"مرحباً <strong>{manager_name}</strong>،",
                "body_1": f"تهانينا! تم تسجيل مطعمك <strong>{restaurant_name}</strong> بنجاح للمشاركة في مرحلتنا التجريبية في الدار البيضاء.",
                "next_steps_title": "الخطوات التالية:",
                "step_1": "سيتصل بك فريقنا خلال 24 ساعة.",
                "step_2": "مكالمة الإعداد والتكوين.",
                "step_3": "إطلاق قناة الطلب الخاصة بك على واتساب.",
                "sign_off": "فريق GEQO",
                "rights_reserved": "جميع الحقوق محفوظة.",
            },
        }

        t = translations.get(locale, translations["fr"])
        params = {
            "manager_name": manager_name,
            "restaurant_name": restaurant_name,
            "locale": locale,
            "dir": "rtl" if locale == "ar" else "ltr",
            "align": "right" if locale == "ar" else "left",
            **t,
        }

        html_content = Template(html_template).safe_substitute(params)
        text_content = (
            f"Welcome to the GEQO Pilot, {manager_name}!\n"
            f"Your restaurant {restaurant_name} is successfully registered.\n"
            f"We will be in touch shortly for the onboarding call."
        )

        return await EmailService._send_email_with_retries(email, subject, text_content, html_content)

    @staticmethod
    async def send_admin_signup_notification(manager_name: str, restaurant_name: str, email: str, whatsapp_number: str, card_code: str):
        """Sends notification to admin@geqo.com when a new signup occurs."""
        try:
            with open("app/templates/email/admin_new_signup.html", "r") as f:
                html_template = f.read()
        except FileNotFoundError:
            html_template = "<p>New signup: $restaurant_name</p>"

        subject = f"🚀 New Beta Signup: {restaurant_name}"
        params = {
            "manager_name": manager_name,
            "restaurant_name": restaurant_name,
            "email": email,
            "whatsapp_number": whatsapp_number,
            "card_code": card_code,
        }

        html_content = Template(html_template).safe_substitute(params)
        text_content = f"New Signup:\nRestaurant: {restaurant_name}\nManager: {manager_name}\nEmail: {email}\nWhatsApp: {whatsapp_number}\nCard: {card_code}"

        return await EmailService._send_email_with_retries(settings.ADMIN_NOTIFICATION_EMAIL, subject, text_content, html_content)

    @staticmethod
    async def send_invite_email(email: str, setup_token: str):
        # URL format: /?setup_token= (not /setup?token=)
        # Reason 1: Cloudflare Pages serves the SPA at root — /setup is a 404.
        # Reason 2: app.js reads urlParams.get('setup_token'), not 'token'.
        setup_link = f"https://app.mygeqo.com/?setup_token={setup_token}"
        subject = "Set up your GEQO Manager Account"
        text_content = f"Click here to set your password: {setup_link}"
        html_content = f"<p>Click <a href='{setup_link}'>here</a> to set your password.</p>"
        return await EmailService._send_email_with_retries(email, subject, text_content, html_content)

    @staticmethod
    async def send_staff_invite_email(email: str, role: str, setup_token: str):
        # Same URL fix as send_invite_email — /?setup_token= required for SPA routing.
        setup_link = f"https://app.mygeqo.com/?setup_token={setup_token}"
        role_display = role.replace("_", " ").title()
        subject = f"You've been invited to GEQO as {role_display}"
        text_content = f"Click here to activate your {role_display} account: {setup_link}"
        html_content = f"<p>Click <a href='{setup_link}'>here</a> to activate your {role_display} account.</p>"
        return await EmailService._send_email_with_retries(email, subject, text_content, html_content)

    @staticmethod
    async def send_admin_data_deletion_notification(phone_number: str, reason: str, request_id: int):
        """Notifies compliance admin of a new CNDP data-deletion request (30-day SLA)."""
        subject = f"🗑️ Data Deletion Request #{request_id} — action required within 30 days"
        text_content = (
            f"A customer has requested erasure of their personal data under CNDP Law 09-08.\n\n"
            f"Request ID: {request_id}\n"
            f"Phone number: {phone_number}\n"
            f"Reason: {reason}\n\n"
            f"This request must be fulfilled within 30 days of submission."
        )
        html_content = (
            f"<p>A customer has requested erasure of their personal data under CNDP Law 09-08.</p>"
            f"<ul>"
            f"<li><strong>Request ID:</strong> {request_id}</li>"
            f"<li><strong>Phone number:</strong> {phone_number}</li>"
            f"<li><strong>Reason:</strong> {reason}</li>"
            f"</ul>"
            f"<p>This request must be fulfilled within <strong>30 days</strong> of submission.</p>"
        )
        return await EmailService._send_email_with_retries(settings.ADMIN_NOTIFICATION_EMAIL, subject, text_content, html_content)

    @staticmethod
    async def send_password_reset_email(email: str, reset_token: str):
        # URL format: /?reset_token= matching app.js URLSearchParams check
        reset_link = f"https://app.mygeqo.com/?reset_token={reset_token}"
        subject = "Reset Your Password"
        text_content = f"Click here to reset your password: {reset_link}"
        html_content = f"<p>Click <a href='{reset_link}'>here</a> to reset your password.</p>"
        return await EmailService._send_email_with_retries(email, subject, text_content, html_content)

    @staticmethod
    async def send_contact_message(category: str, name: str, email: str, message: str, whatsapp: str = None):
        """Forwards a marketing-site Contact Us submission to the relevant mailbox.

        No database persistence for v1 — this is an email-forward only. Reply-to
        is set to the submitter's own address so the receiving team can just hit
        reply.
        """
        target_email = "sales@mygeqo.com" if category == "sales" else "support@mygeqo.com"
        subject = f"[GEQO Contact — {category.upper()}] {name}"

        text_lines = [
            f"Name: {name}",
            f"Email: {email}",
        ]
        if whatsapp:
            text_lines.append(f"WhatsApp: {whatsapp}")
        text_lines.append("")
        text_lines.append("Message:")
        text_lines.append(message)
        text_content = "\n".join(text_lines)

        whatsapp_html = f"<p><strong>WhatsApp:</strong> {whatsapp}</p>" if whatsapp else ""
        html_content = (
            f"<p><strong>Name:</strong> {name}</p>"
            f"<p><strong>Email:</strong> {email}</p>"
            f"{whatsapp_html}"
            f"<p><strong>Message:</strong></p>"
            f"<p>{message}</p>"
        )

        return await EmailService._send_email_with_retries(
            target_email, subject, text_content, html_content, reply_to=email
        )
