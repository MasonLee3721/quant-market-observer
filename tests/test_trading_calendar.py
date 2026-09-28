"""Tests for Taiwan market trading-date resolution."""

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from qmo.trading_calendar import load_market_holidays, resolve_latest_trading_date

TAIPEI = ZoneInfo("Asia/Taipei")


def test_latest_after_close_uses_same_weekday() -> None:
    now = datetime(2026, 9, 28, 16, 0, tzinfo=TAIPEI)
    assert resolve_latest_trading_date(now) == date(2026, 9, 28)


def test_latest_before_close_uses_previous_session() -> None:
    now = datetime(2026, 9, 28, 10, 0, tzinfo=TAIPEI)
    assert resolve_latest_trading_date(now) == date(2026, 9, 25)


def test_latest_skips_weekend_and_explicit_market_holiday() -> None:
    now = datetime(2026, 10, 12, 10, 0, tzinfo=TAIPEI)
    holidays = {date(2026, 10, 9)}
    assert resolve_latest_trading_date(now, holidays=holidays) == date(2026, 10, 8)


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        resolve_latest_trading_date(datetime(2026, 9, 28, 16, 0))


def test_holiday_file_fails_closed(tmp_path: Path) -> None:
    calendar = tmp_path / "holidays.csv"
    calendar.write_text("date\n2026-10-09\n", encoding="utf-8")
    assert load_market_holidays(calendar) == {date(2026, 10, 9)}

    calendar.write_text("date\nnot-a-date\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid market holiday"):
        load_market_holidays(calendar)

    with pytest.raises(FileNotFoundError):
        load_market_holidays(tmp_path / "missing.csv")
