"""Parsers for values that arrive as free text from a speech model.

Everything Vogent sends is a string that an LLM produced from what it heard. A
phone number may arrive as spoken words, a date as "next Tuesday". These parsers
accept a deliberately limited, documented set and return None otherwise, so the
function can answer `invalid_input` and let the flow re-ask. They never guess.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

SPOKEN_DIGITS = {
    "zero": "0",
    "oh": "0",
    "o": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

#: Appointments are offered in this window, at a fixed hour, because the simulated
#: scheduler has no real calendar to consult.
DEFAULT_APPOINTMENT_HOUR = 10
MAX_DAYS_AHEAD = 120


def normalize_phone(raw: str | None) -> str | None:
    """Return an E.164 US number, or None if the input cannot be read confidently.

    Handles digits, common separators, and digits spoken as words, which is what a
    transcript of "five five five" turns into.
    """
    if not raw:
        return None
    text = raw.strip().lower()

    words = re.split(r"[\s,.-]+", text)
    converted = "".join(SPOKEN_DIGITS.get(word, word) for word in words if word)
    digits = re.sub(r"\D", "", converted)

    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return f"+1{digits}"


def parse_preferred_date(raw: str | None, *, now: datetime | None = None) -> datetime | None:
    """Read a requested appointment day from natural phrasing.

    Supported: ISO dates, `tomorrow`, `next <weekday>`, a bare `<weekday>`,
    `<Month> <day>`, and `MM/DD`. Anything else returns None on purpose: booking a
    guessed date is worse than asking the caller again.
    """
    if not raw:
        return None
    now = now or datetime.now(UTC)
    text = raw.strip().lower()

    iso = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if iso:
        return _at_hour(datetime(int(iso[1]), int(iso[2]), int(iso[3]), tzinfo=UTC), now)

    if "tomorrow" in text:
        return _at_hour(now + timedelta(days=1), now)
    if "today" in text:
        return _at_hour(now, now)

    for name, index in WEEKDAYS.items():
        if name in text:
            ahead = (index - now.weekday()) % 7
            if ahead == 0:
                ahead = 7  # "Tuesday" said on a Tuesday means the next one
            if "next" in text and ahead < 7:
                ahead += 7
            return _at_hour(now + timedelta(days=ahead), now)

    for name, month in MONTHS.items():
        match = re.search(rf"{name}\s+(\d{{1,2}})", text)
        if match:
            day = int(match[1])
            year = now.year + (1 if month < now.month else 0)
            try:
                return _at_hour(datetime(year, month, day, tzinfo=UTC), now)
            except ValueError:
                return None

    numeric = re.search(r"\b(\d{1,2})/(\d{1,2})\b", text)
    if numeric:
        month, day = int(numeric[1]), int(numeric[2])
        year = now.year + (1 if month < now.month else 0)
        try:
            return _at_hour(datetime(year, month, day, tzinfo=UTC), now)
        except ValueError:
            return None

    return None


def _at_hour(when: datetime, now: datetime) -> datetime | None:
    slot = when.replace(hour=DEFAULT_APPOINTMENT_HOUR, minute=0, second=0, microsecond=0)
    if slot <= now or slot > now + timedelta(days=MAX_DAYS_AHEAD):
        # A date in the past, or absurdly far ahead, means we misread it.
        return None
    return slot
