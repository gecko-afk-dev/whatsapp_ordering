"""
Operating Hours utility.

Provides `is_restaurant_open(restaurant)` — the single source of truth for
whether a restaurant is currently serving orders.

Schedule format (stored as JSON string in `restaurant.operating_hours`):
    [
      { "day": "Monday",    "isOpen": true,  "open": "11:00", "close": "23:30" },
      { "day": "Tuesday",   "isOpen": false, "open": "11:00", "close": "23:30" },
      ...
    ]

Day names match the JavaScript `Settings.js` weeklyHours array exactly.
Midnight rollovers are supported: e.g. open="22:00", close="02:00" means
the restaurant closes at 2 AM the following day.
"""
import json
import logging
from datetime import datetime, time

logger = logging.getLogger(__name__)

# Map Python weekday() (0=Monday) to the day names used in the JSON
_WEEKDAY_NAMES = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
]


def _parse_time(t: str) -> time:
    """Parse 'HH:MM' into a time object."""
    h, m = t.strip().split(":")
    return time(int(h), int(m))


def is_restaurant_open(restaurant) -> bool:
    """
    Return True if the restaurant should accept orders right now.

    Priority:
      1. If `is_accepting_orders` is False (manual override) → always closed.
      2. If `operating_hours` is unset/null/empty → assume 24/7, return True.
      3. Parse the schedule JSON and check the current Casablanca time against
         today's window. Midnight rollovers are handled correctly.
    """
    # --- 1. Manual override ---
    if not restaurant.is_accepting_orders:
        return False

    # --- 2. No schedule set → always open ---
    if not restaurant.operating_hours:
        return True

    # --- 3. Parse schedule and evaluate ---
    try:
        import pytz
        tz = pytz.timezone("Africa/Casablanca")
        now = datetime.now(tz)
        today_name = _WEEKDAY_NAMES[now.weekday()]
        now_time = now.time().replace(second=0, microsecond=0)

        schedule = json.loads(restaurant.operating_hours)

        # Find today's entry (case-insensitive match)
        today_entry = next(
            (d for d in schedule if d.get("day", "").lower() == today_name.lower()),
            None
        )

        if not today_entry or not today_entry.get("isOpen", False):
            return False

        open_t = _parse_time(today_entry["open"])
        close_t = _parse_time(today_entry["close"])

        if open_t <= close_t:
            # Normal window, e.g. 11:00 - 23:30
            return open_t <= now_time <= close_t
        else:
            # Midnight rollover, e.g. 22:00 - 02:00
            # Restaurant is open if current time is AFTER open OR BEFORE close
            return now_time >= open_t or now_time <= close_t

    except Exception as e:
        logger.warning("[is_restaurant_open] Failed to evaluate hours: %s", e)
        # Fail open — don't block orders due to a parse error
        return True
