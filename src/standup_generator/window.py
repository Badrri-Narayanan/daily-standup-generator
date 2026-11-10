"""The look-back window: start of the previous working day until now."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo

from .models import TimeWindow

_DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_MAX_LOOKBACK_DAYS = 31


def resolve_tz(name: str | None) -> tzinfo:
    if name:
        return ZoneInfo(name)
    return datetime.now().astimezone().tzinfo


def _midnight(day: date, tz: tzinfo | None) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz)


def compute_window(
    now: datetime,
    working_days: list[str],
    holidays: list[date],
    since: date | None = None,
) -> TimeWindow:
    if since is not None:
        return TimeWindow(start=_midnight(since, now.tzinfo), end=now)
    allowed = {d.lower() for d in working_days}
    skip = set(holidays)
    day = now.date()
    for _ in range(_MAX_LOOKBACK_DAYS):
        day -= timedelta(days=1)
        if _DAY_NAMES[day.weekday()] in allowed and day not in skip:
            return TimeWindow(start=_midnight(day, now.tzinfo), end=now)
    raise ValueError(f"no working day found in last {_MAX_LOOKBACK_DAYS} days")
