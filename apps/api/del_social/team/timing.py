"""When a post goes out. Computed by code from the Team Lead's choice, never taken from a model.

Azerbaijan has had no daylight saving time since 2016: Baku is UTC+4 all year.
"""
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Literal

BAKU = timezone(timedelta(hours=4), "Asia/Baku")
MORNING = time(10, 0)
EVENING = time(19, 0)  # default best time until the Analyst measures the page's own

When = Literal["after_approval", "today_evening", "tomorrow_morning", "tomorrow_evening", "specific"]


class TimingError(ValueError):
    """Safe to show."""


def resolve(when: When, day: str | None = None, at: str | None = None, now: datetime | None = None) -> datetime | None:
    """UTC publish time, or None for "publish as soon as it is approved"."""
    now = (now or datetime.now(UTC)).astimezone(BAKU)
    if when == "after_approval":
        return None
    if when == "today_evening":
        target = datetime.combine(now.date(), EVENING, BAKU)
        if target <= now + timedelta(minutes=15):
            target += timedelta(days=1)
    elif when == "tomorrow_morning":
        target = datetime.combine(now.date() + timedelta(days=1), MORNING, BAKU)
    elif when == "tomorrow_evening":
        target = datetime.combine(now.date() + timedelta(days=1), EVENING, BAKU)
    else:
        try:
            d = date.fromisoformat(day or "")
            h, m = (int(x) for x in (at or "19:00").split(":"))
            target = datetime.combine(d, time(h, m), BAKU)
        except (ValueError, TypeError):
            raise TimingError("The date or time is not valid") from None
        if target <= now:
            raise TimingError("That time has already passed")
        if target > now + timedelta(days=60):
            raise TimingError("Posts can be scheduled at most 60 days ahead")
    return target.astimezone(UTC)


def baku_label(when_utc: datetime | None) -> str:
    return when_utc.astimezone(BAKU).strftime("%d.%m.%Y %H:%M") if when_utc else ""
