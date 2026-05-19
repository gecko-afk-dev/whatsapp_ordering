import logging

logger = logging.getLogger(__name__)

class EmailService:
    @staticmethod
    async def send_invite_email(email: str, setup_token: str):
        """Mock function to send an invite email.
        In production, replace with real SMTP or API call (SendGrid, SES).
        """
        setup_link = f"http://localhost:8000/static/index.html?setup_token={setup_token}"
        logger.info(f"\\n{'='*50}\\nMOCK EMAIL SENT TO: {email}\\nSubject: Set up your GEQO Manager Account\\nBody: Click here to set your password: {setup_link}\\n{'='*50}\\n")

    @staticmethod
    async def send_password_reset_email(email: str, reset_token: str):
        """Mock function to send a password reset email."""
        reset_link = f"http://localhost:8000/static/index.html?reset_token={reset_token}"
        logger.info(f"\\n{'='*50}\\nMOCK EMAIL SENT TO: {email}\\nSubject: Reset Your Password\\nBody: Click here to reset your password: {reset_link}\\n{'='*50}\\n")
