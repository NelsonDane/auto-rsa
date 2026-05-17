"""Locks the NYSE-calendar / pre-split-deadline math (Apps Script parity)."""

from datetime import date

from src.edgar.market_calendar import (
    add_trading_days,
    is_nyse_holiday,
    parse_effective_date,
    presplit_deadline_text,
    previous_market_day,
)


def test_2026_nyse_holidays():
    holidays = {
        date(2026, 1, 1),    # New Year's Day (Thu)
        date(2026, 1, 19),   # MLK (3rd Mon Jan)
        date(2026, 2, 16),   # Presidents (3rd Mon Feb)
        date(2026, 4, 3),    # Good Friday (Easter 4/5/2026)
        date(2026, 5, 25),   # Memorial (last Mon May)
        date(2026, 6, 19),   # Juneteenth (Fri)
        date(2026, 7, 3),    # Independence observed (4th is Sat)
        date(2026, 9, 7),    # Labor (1st Mon Sep)
        date(2026, 11, 26),  # Thanksgiving (4th Thu Nov)
        date(2026, 12, 25),  # Christmas (Fri)
    }
    for h in holidays:
        assert is_nyse_holiday(h), h
    assert not is_nyse_holiday(date(2026, 7, 6))
    assert not is_nyse_holiday(date(2026, 3, 17))


def test_previous_market_day_skips_weekend_and_holiday():
    # Mon 7/6/2026: back over Sun, Sat, observed-holiday Fri 7/3 -> Thu 7/2.
    assert previous_market_day(date(2026, 7, 6)) == date(2026, 7, 2)
    # Plain Tuesday -> Monday.
    assert previous_market_day(date(2026, 3, 17)) == date(2026, 3, 16)
    # Monday -> previous Friday.
    assert previous_market_day(date(2026, 3, 16)) == date(2026, 3, 13)


def test_presplit_deadline_text():
    assert presplit_deadline_text(date(2026, 7, 6)) == (
        "July 02 by 4pm (Eastern Time)"
    )
    assert presplit_deadline_text("") == "—"
    assert presplit_deadline_text("not a date") == "—"


def test_parse_effective_date_formats():
    for s in ("2026-06-01", "6/1/2026", "June 1, 2026", "Jun 1 2026"):
        assert parse_effective_date(s) == date(2026, 6, 1), s
    assert parse_effective_date("") is None
    assert parse_effective_date(date(2026, 6, 1)) == date(2026, 6, 1)


def test_add_trading_days():
    # Fri 3/13/2026 + 1 weekday -> Mon 3/16 (holidays ignored, per source).
    assert add_trading_days(date(2026, 3, 13), 1) == date(2026, 3, 16)
    assert add_trading_days(date(2026, 3, 16), 5) == date(2026, 3, 23)
