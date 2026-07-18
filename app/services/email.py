import logging
import smtplib
import asyncio
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from string import Template
from app.core.config import settings

logger = logging.getLogger(__name__)

class EmailService:
    @staticmethod
    def _send_email_sync(to_email: str, subject: str, text_content: str, html_content: str = None):
        """Synchronous SMTP sending logic using standard library."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{settings.SMTP_SENDER_NAME} <{settings.SMTP_USER}>"
        msg["To"] = to_email

        # Attach parts
        msg.attach(MIMEText(text_content, "plain"))
        if html_content:
            msg.attach(MIMEText(html_content, "html"))

        try:
            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=5.0) as server:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(settings.SMTP_USER, to_email, msg.as_string())
            logger.info(f"Successfully sent email to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {str(e)}")
            return False

    @staticmethod
    async def _send_email_async(to_email: str, subject: str, text_content: str, html_content: str = None):
        """Run the synchronous SMTP logic in a thread pool."""
        return await asyncio.to_thread(
            EmailService._send_email_sync, to_email, subject, text_content, html_content
        )

    @staticmethod
    async def _send_email_with_retries(to_email: str, subject: str, text_content: str, html_content: str = None, retries: int = 3, delay_seconds: float = 1.0):
        """Retry transient email failures a few times before giving up."""
        last_error = None
        for attempt in range(retries):
            try:
                return await EmailService._send_email_async(to_email, subject, text_content, html_content)
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
        # Load the HTML template (we will create this template in the next workstream)
        try:
            with open("app/templates/email/beta_confirmation.html", "r") as f:
                html_template = f.read()
        except FileNotFoundError:
            logger.warning("Beta confirmation template not found, using basic HTML.")
            html_template = "<h1>Welcome to the Pilot, $manager_name!</h1><p>$restaurant_name is registered.</p>"

        # Determine subject based on locale
        subjects = {
            "en": "Welcome to the GEQO Pilot!",
            "fr": "Bienvenue dans le pilote GEQO !",
            "ar": "مرحباً بك في البرنامج التجريبي لـ GEQO!"
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
                "rights_reserved": "All rights reserved."
            },
            "fr": {
                "greeting": f"Bonjour <strong>{manager_name}</strong>,",
                "body_1": f"Félicitations ! Votre restaurant <strong>{restaurant_name}</strong> est bien enregistré pour participer à notre phase pilote à Casablanca.",
                "next_steps_title": "Prochaines étapes :",
                "step_1": "Notre équipe vous contactera sous 24h.",
                "step_2": "Appel d'intégration et configuration.",
                "step_3": "Lancement de votre canal de commande WhatsApp.",
                "sign_off": "L'équipe GEQO",
                "rights_reserved": "Tous droits réservés."
            },
            "ar": {
                "greeting": f"مرحباً <strong>{manager_name}</strong>،",
                "body_1": f"تهانينا! تم تسجيل مطعمك <strong>{restaurant_name}</strong> بنجاح للمشاركة في مرحلتنا التجريبية في الدار البيضاء.",
                "next_steps_title": "الخطوات التالية:",
                "step_1": "سيتصل بك فريقنا خلال 24 ساعة.",
                "step_2": "مكالمة الإعداد والتكوين.",
                "step_3": "إطلاق قناة الطلب الخاصة بك على واتساب.",
                "sign_off": "فريق GEQO",
                "rights_reserved": "جميع الحقوق محفوظة."
            }
        }
        
        t = translations.get(locale, translations["fr"])

        # Prepare parameters for substitution
        params = {
            "manager_name": manager_name,
            "restaurant_name": restaurant_name,
            "locale": locale,
            "dir": "rtl" if locale == "ar" else "ltr",
            "align": "right" if locale == "ar" else "left",
            **t
        }

        # Safe substitute to avoid errors if some vars are missing
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
            "card_code": card_code
        }

        html_content = Template(html_template).safe_substitute(params)
        text_content = f"New Signup:\nRestaurant: {restaurant_name}\nManager: {manager_name}\nEmail: {email}\nWhatsApp: {whatsapp_number}\nCard: {card_code}"

        return await EmailService._send_email_with_retries(settings.ADMIN_NOTIFICATION_EMAIL, subject, text_content, html_content)

    @staticmethod
    async def send_invite_email(email: str, setup_token: str):
        setup_link = f"https://app.mygeqo.com/setup?token={setup_token}"
        subject = "Set up your GEQO Manager Account"
        text_content = f"Click here to set your password: {setup_link}"
        html_content = f"<p>Click <a href='{setup_link}'>here</a> to set your password.</p>"
        return await EmailService._send_email_with_retries(email, subject, text_content, html_content)

    @staticmethod
    async def send_staff_invite_email(email: str, role: str, setup_token: str):
        setup_link = f"https://app.mygeqo.com/setup?token={setup_token}"
        role_display = role.replace("_", " ").title()
        subject = f"You've been invited to GEQO as {role_display}"
        text_content = f"Click here to activate your {role_display} account: {setup_link}"
        html_content = f"<p>Click <a href='{setup_link}'>here</a> to activate your {role_display} account.</p>"
        return await EmailService._send_email_with_retries(email, subject, text_content, html_content)

    @staticmethod
    async def send_password_reset_email(email: str, reset_token: str):
        reset_link = f"https://app.mygeqo.com/reset-password?token={reset_token}"
        subject = "Reset Your Password"
        text_content = f"Click here to reset your password: {reset_link}"
        html_content = f"<p>Click <a href='{reset_link}'>here</a> to reset your password.</p>"
        return await EmailService._send_email_with_retries(email, subject, text_content, html_content)
