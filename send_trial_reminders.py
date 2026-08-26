"""
send_trial_reminders.py — Daily beta trial "3 days left" WhatsApp nudge

Not a migration — a recurring operational script. Run this once a day via
crontab on the app server:

    0 10 * * * cd /root/whatsapp_ordering && /root/whatsapp_ordering/venv/bin/python3 send_trial_reminders.py >> /var/log/geqo/trial_reminders.log 2>&1

(10:00 server time — adjust to land during Casablanca daytime hours, same
spirit as the meal-time-window guard in app/services/hours.py. Use the venv
Python, not system Python — same lesson as the other standalone scripts here.)

What it does:
- Finds every BetaSignup where trial_ends_at falls within the next 3 days
  (and hasn't already passed) and trial_reminder_sent is still False.
- Sends one WhatsApp text nudge per signup, localized via BetaSignup.locale.
- Marks trial_reminder_sent = True right after a successful send, so a
  restaurant is never nudged twice even if this runs more than once a day.

What it deliberately does NOT do:
- Block orders, downgrade the account, or take any action once the trial
  actually lapses — that enforcement behavior is still an open decision.
  This script only sends the advance warning.

Safe to re-run — trial_reminder_sent is the guard against duplicate sends,
mirroring the IF-NOT-EXISTS-guard discipline of the migration scripts here.
"""
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

REMINDER_WINDOW_DAYS = 3

MESSAGES = {
    "en": (
        "Hi {manager_name}! Quick heads-up: your GEQO trial for "
        "{restaurant_name} ends in {days_left} day(s). No action needed if "
        "you'd like to continue — our team will reach out about picking a "
        "plan. Questions? Just reply here."
    ),
    "fr": (
        "Bonjour {manager_name} ! Petit rappel : votre essai GEQO pour "
        "{restaurant_name} se termine dans {days_left} jour(s). Aucune "
        "action requise si vous souhaitez continuer — notre équipe vous "
        "contactera pour choisir une formule. Des questions ? Répondez ici."
    ),
    "ar": (
        "مرحباً {manager_name}! تذكير سريع: تنتهي فترة تجربة GEQO الخاصة "
        "بـ {restaurant_name} خلال {days_left} يوم/أيام. لا حاجة لأي إجراء "
        "إذا كنت ترغب في المتابعة — سيتواصل معك فريقنا لاختيار خطة. "
        "أسئلة؟ فقط أجب هنا."
    ),
}


async def run():
    from app.core.config import settings
    from app.models import BetaSignup
    from app.services.whatsapp import WhatsAppService

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    now = datetime.utcnow()
    window_end = now + timedelta(days=REMINDER_WINDOW_DAYS)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(BetaSignup).where(
                BetaSignup.trial_ends_at.isnot(None),
                BetaSignup.trial_ends_at > now,
                BetaSignup.trial_ends_at <= window_end,
                BetaSignup.trial_reminder_sent.is_(False),
            )
        )
        due = result.scalars().all()

        if not due:
            logger.info("No trial reminders due right now.")
            await engine.dispose()
            return

        logger.info("Found %d signup(s) due for a trial reminder.", len(due))
        wa = WhatsAppService()
        sent_count = 0

        for signup in due:
            days_left = max((signup.trial_ends_at - now).days, 0) + 1  # round up to whole days
            template = MESSAGES.get(signup.locale, MESSAGES["fr"])
            text = template.format(
                manager_name=signup.manager_name,
                restaurant_name=signup.restaurant_name,
                days_left=days_left,
            )
            try:
                await wa.send_text_message(signup.whatsapp_number, text)
            except Exception:
                logger.exception(
                    "Failed to send trial reminder for signup_id=%s (%s) — will retry on next run.",
                    signup.id, signup.restaurant_name,
                )
                continue  # don't mark as sent — retry tomorrow

            await db.execute(
                update(BetaSignup).where(BetaSignup.id == signup.id).values(trial_reminder_sent=True)
            )
            await db.commit()
            sent_count += 1
            logger.info("Sent trial reminder to %s (signup_id=%s).", signup.restaurant_name, signup.id)

        logger.info("Done. %d/%d reminder(s) sent.", sent_count, len(due))

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
