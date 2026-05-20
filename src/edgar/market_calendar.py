"""NYSE holiday calendar + pre-split buy deadline.

Faithful port of the Apps Script date logic (previousMarketDay_,
getNyseHolidaySet_, easterSunday_, computePreSplitText_, ...). The
pre-split *buy deadline* is the last NYSE session strictly before the
split's effective date — buying on/after the effective date misses the
round-up.

JS ``Date.getDay()`` is Sunday=0..Saturday=6; helpers below replicate
that convention so the holiday math matches the source 1:1.
"""

from __future__ import annotations

import contextlib
from datetime import date, datetime
from functools import lru_cache

_SAT, _SUN = 6, 0


def _js_dow(d: date) -> int:
    """JS getDay(): Sunday=0 .. Saturday=6."""
    return (d.weekday() + 1) % 7


def _observed_fixed(year: int, month: int, day: int) -> date:
    d = date(year, month, day)
    dow = _js_dow(d)
    if dow == _SAT:
        return date.fromordinal(d.toordinal() - 1)
    if dow == _SUN:
        return date.fromordinal(d.toordinal() + 1)
    return d


def _nth_weekday(year: int, month: int, js_weekday: int, n: int) -> date:
    first = date(year, month, 1)
    first_dow = _js_dow(first)
    offset = (js_weekday - first_dow + 7) % 7
    return date(year, month, 1 + offset + (n - 1) * 7)


def _last_weekday(year: int, month: int, js_weekday: int) -> date:
    nxt = month % 12 + 1
    nyear = year + (1 if month == 12 else 0)  # noqa: PLR2004
    last = date.fromordinal(date(nyear, nxt, 1).toordinal() - 1)
    offset = (_js_dow(last) - js_weekday + 7) % 7
    return date.fromordinal(last.toordinal() - offset)


def _easter_sunday(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ln = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ln) // 451
    month = (h + ln - 7 * m + 114) // 31
    day = ((h + ln - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _good_friday(year: int) -> date:
    return date.fromordinal(_easter_sunday(year).toordinal() - 2)


@lru_cache(maxsize=16)
def _nyse_holidays(year: int) -> frozenset[date]:
    return frozenset(
        {
            _observed_fixed(year, 1, 1),  # New Year's Day
            _observed_fixed(year, 6, 19),  # Juneteenth
            _observed_fixed(year, 7, 4),  # Independence Day
            _observed_fixed(year, 12, 25),  # Christmas
            _nth_weekday(year, 1, 1, 3),  # MLK (3rd Mon Jan)
            _nth_weekday(year, 2, 1, 3),  # Presidents (3rd Mon Feb)
            _good_friday(year),
            _last_weekday(year, 5, 1),  # Memorial (last Mon May)
            _nth_weekday(year, 9, 1, 1),  # Labor (1st Mon Sep)
            _nth_weekday(year, 11, 4, 4),  # Thanksgiving (4th Thu Nov)
        },
    )


def is_nyse_holiday(d: date) -> bool:
    """Return True if the NYSE is closed for a holiday on ``d``."""
    return d in _nyse_holidays(d.year)


def previous_market_day(d: date) -> date:
    """Return the NYSE session strictly before ``d`` (skips closures)."""
    cur = d
    while True:
        cur = date.fromordinal(cur.toordinal() - 1)
        if _js_dow(cur) in {_SAT, _SUN}:
            continue
        if is_nyse_holiday(cur):
            continue
        return cur


def add_trading_days(d: date, n: int) -> date:
    """``d`` plus ``n`` weekdays (matches addTradingDays_; ignores holidays)."""
    cur = d
    added = 0
    while added < n:
        cur = date.fromordinal(cur.toordinal() + 1)
        if _js_dow(cur) not in {_SAT, _SUN}:
            added += 1
    return cur


_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%B %d %Y",
    "%b %d %Y",
    "%Y-%m-%dT%H:%M:%S",
)


def parse_effective_date(value: object) -> date | None:
    """Best-effort parse of an effective-date cell/string to a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value or "").strip()
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        with contextlib.suppress(ValueError):
            return datetime.strptime(s, fmt).date()  # noqa: DTZ007
    return None


def presplit_deadline_text(effective: object) -> str:
    """'<Month DD> by 4pm (Eastern Time)' for the last buy day, or '—'."""
    eff = parse_effective_date(effective)
    if eff is None:
        return "—"
    pre = previous_market_day(eff)
    return f"{pre:%B %d} by 4pm (Eastern Time)"
