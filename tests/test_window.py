from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from standup_generator.window import compute_window, resolve_tz

TZ = ZoneInfo("Europe/London")
WD = ["mon", "tue", "wed", "thu", "fri"]


def test_tuesday_goes_to_monday():
    w = compute_window(datetime(2026, 11, 10, 9, 0, tzinfo=TZ), WD, [])
    assert w.start == datetime(2026, 11, 9, 0, 0, tzinfo=TZ)


def test_monday_goes_to_friday():
    assert compute_window(datetime(2026, 11, 9, 9, tzinfo=TZ), WD, []).start.date() == date(2026, 11, 6)


def test_skips_holiday():
    w = compute_window(datetime(2026, 11, 10, 9, tzinfo=TZ), WD, [date(2026, 11, 9)])
    assert w.start.date() == date(2026, 11, 6)


def test_since_override():
    w = compute_window(datetime(2026, 11, 10, 9, tzinfo=TZ), WD, [], since=date(2026, 11, 1))
    assert w.start == datetime(2026, 11, 1, 0, 0, tzinfo=TZ)


def test_end_is_now():
    now = datetime(2026, 11, 10, 9, tzinfo=TZ)
    assert compute_window(now, WD, []).end == now


def test_no_working_days_raises():
    with pytest.raises(ValueError):
        compute_window(datetime(2026, 11, 10, 9, tzinfo=TZ), [], [])


def test_resolve_tz_named_and_local():
    assert resolve_tz("Europe/London") == TZ
    assert resolve_tz(None) is not None
