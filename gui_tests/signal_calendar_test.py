"""Calendar bucketing helper for the Signals tab."""

from __future__ import annotations

from datetime import datetime

from src.gui.app import _bucket_signals_by_day
from src.gui.core.sheets import Signal


def _sig(ticker: str, eff: str) -> Signal:
    return Signal(
        created_at="2026-05-01", ticker=ticker, action="buy",
        ratio="1-for-40", effective_date=eff, presplit_deadline="",
        fractional_policy="ROUND_UP", confidence="0.93",
        source="SEC_EFTS", key=f"K-{ticker}-{eff}", status="PENDING",
    )


def test_window_runs_7_days_back_through_30_days_forward():
    today = datetime(2026, 6, 1)
    days, _by_day = _bucket_signals_by_day([], today=today)
    assert days[0].date() == datetime(2026, 5, 25).date()  # 7 days back
    assert days[-1].date() == datetime(2026, 7, 1).date()  # 30 days forward
    assert len(days) == 38  # 7 past + today + 30 future


def test_signals_bucketed_by_iso_date():
    today = datetime(2026, 6, 1)
    sigs = [
        _sig("ACME", "2026-06-05"),
        _sig("BETA", "2026-06-05"),
        _sig("GAMMA", "2026-06-10"),
    ]
    _days, by_day = _bucket_signals_by_day(sigs, today=today)
    assert {s.ticker for s in by_day["2026-06-05"]} == {"ACME", "BETA"}
    assert [s.ticker for s in by_day["2026-06-10"]] == ["GAMMA"]


def test_signals_outside_window_are_excluded():
    today = datetime(2026, 6, 1)
    sigs = [
        _sig("OLD", "2026-05-10"),   # 22 days back — outside 7d past window
        _sig("FAR", "2026-08-15"),   # 75 days forward — outside 30d window
        _sig("IN",  "2026-06-15"),
    ]
    _days, by_day = _bucket_signals_by_day(sigs, today=today)
    assert "2026-05-10" not in by_day
    assert "2026-08-15" not in by_day
    assert "2026-06-15" in by_day


def test_signals_with_unparseable_dates_are_skipped():
    today = datetime(2026, 6, 1)
    sigs = [
        _sig("GOOD", "2026-06-05"),
        _sig("BAD",  "when convenient"),
        _sig("EMPTY", ""),
    ]
    _days, by_day = _bucket_signals_by_day(sigs, today=today)
    assert "2026-06-05" in by_day
    assert all(s.ticker == "GOOD" for s in by_day["2026-06-05"])


def test_custom_window_sizes():
    today = datetime(2026, 6, 1)
    days, _ = _bucket_signals_by_day(
        [], today=today, past_days=0, forward_days=14,
    )
    assert days[0].date() == today.date()
    assert days[-1].date() == datetime(2026, 6, 15).date()
    assert len(days) == 15
