"""GUI_QUEUE parsing — header validation + row extraction."""

import pytest

from src.gui.core.sheets import SheetsError, parse_values


_HEADER_ROW = [
    "CREATED_AT", "TICKER", "ACTION", "RATIO", "EFFECTIVE_DATE",
    "PRESPLIT_DEADLINE", "FRACTIONAL_POLICY", "CONFIDENCE",
    "SOURCE", "KEY", "STATUS",
]
_GOOD_ROW = [
    "2026-05-01", "ACME", "buy", "1-for-40", "2026-06-01",
    "May 30, 2026", "ROUND_UP", "0.93", "SEC_EFTS", "K-ACME", "PENDING",
]


def test_parse_values_happy_path():
    sigs = parse_values([_HEADER_ROW, _GOOD_ROW])
    assert len(sigs) == 1
    s = sigs[0]
    assert s.ticker == "ACME"
    assert s.effective_date == "2026-06-01"
    assert s.fractional_policy == "ROUND_UP"


def test_missing_effective_date_header_raises_sheeterror():
    """The exact bug from audit finding C3 — typo'd EFFECTIVE_DT
    would silently null the column and let past splits look actionable.
    Must hard-fail at parse time, not at execute time."""
    bad_header = list(_HEADER_ROW)
    bad_header[bad_header.index("EFFECTIVE_DATE")] = "EFFECTIVE_DT"
    with pytest.raises(SheetsError) as exc:
        parse_values([bad_header, _GOOD_ROW])
    assert "EFFECTIVE_DATE" in str(exc.value)


def test_missing_action_header_raises_sheeterror():
    """ACTION drives buy-vs-sell gating; a missing header would let
    every row default to 'buy' silently."""
    bad_header = [h for h in _HEADER_ROW if h != "ACTION"]
    bad_row = [c for h, c in zip(_HEADER_ROW, _GOOD_ROW) if h != "ACTION"]
    with pytest.raises(SheetsError) as exc:
        parse_values([bad_header, bad_row])
    assert "ACTION" in str(exc.value)


def test_no_header_falls_back_to_positional():
    """Backward-compat: a sheet without a header still parses by position."""
    sigs = parse_values([_GOOD_ROW])
    assert len(sigs) == 1
    assert sigs[0].ticker == "ACME"


def test_empty_values_returns_empty():
    assert parse_values([]) == []


def test_row_without_ticker_or_key_is_skipped():
    no_key = list(_GOOD_ROW)
    no_key[_HEADER_ROW.index("KEY")] = ""
    sigs = parse_values([_HEADER_ROW, no_key])
    assert sigs == []
