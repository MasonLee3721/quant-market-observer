"""Taiwan market trading-date resolution for scheduled pipeline runs."""

from __future__ import annotations

import csv
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

TAIPEI_TZ = ZoneInfo("Asia/Taipei")
DEFAULT_MARKET_CLOSE = time(15, 30)


def load_market_holidays(path: Path) -> set[date]:
    """Load explicit market closure dates from a one-column CSV file.

    The first column must contain an ISO date. A header named ``date`` is
    accepted. Invalid or missing files fail closed instead of being ignored.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Market holiday calendar not found: {path}")

    holidays: set[date] = set()
    with path.open(newline="", encoding="utf-8") as handle:
        for row_number, row in enumerate(csv.reader(handle), start=1):
            if not row or not row[0].strip():
                continue
            value = row[0].strip()
            if row_number == 1 and value.lower() == "date":
                continue
            try:
                holidays.add(date.fromisoformat(value))
            except ValueError as exc:
                raise ValueError(
                    f"Invalid market holiday date at {path}:{row_number}: {value!r}"
                ) from exc
    return holidays


def is_trading_day(candidate: date, holidays: Iterable[date] = ()) -> bool:
    """Return whether a date is a weekday not listed as a market closure."""
    return candidate.weekday() < 5 and candidate not in set(holidays)


def resolve_latest_trading_date(
    now: datetime | None = None,
    *,
    holidays: Iterable[date] = (),
    market_close: time = DEFAULT_MARKET_CLOSE,
) -> date:
    """Resolve the latest completed Taiwan trading session candidate.

    Before the post-market cutoff, today's session is not considered complete.
    Callers must still verify that providers returned data for the resolved date;
    this function intentionally never treats an empty response as a valid session.
    """
    current = now or datetime.now(TAIPEI_TZ)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local_now = current.astimezone(TAIPEI_TZ)
    candidate = local_now.date()
    if local_now.timetz().replace(tzinfo=None) < market_close:
        candidate -= timedelta(days=1)

    holiday_set = set(holidays)
    while not is_trading_day(candidate, holiday_set):
        candidate -= timedelta(days=1)
    return candidate
