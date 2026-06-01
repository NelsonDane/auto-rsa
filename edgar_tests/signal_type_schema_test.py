"""Phase 5b — SIGNAL_TYPE column threaded through producer + sheets."""

from __future__ import annotations

from src.edgar import producer
from src.edgar.classify import (
    SIGNAL_TYPE_ROUND_UP_REVERSE,
    SIGNAL_TYPE_SPECIAL_DIV,
    SIGNAL_TYPE_SPIN_OFF,
)
from src.edgar.fetch import Hit
from src.gui.core.sheets import Signal, parse_values

# Existing 11-column header (pre-Phase 5b) — sheets written by the
# un-upgraded Apps Script. parse_values must handle this gracefully.
_LEGACY_HEADER = [
    "CREATED_AT", "TICKER", "ACTION", "RATIO", "EFFECTIVE_DATE",
    "PRESPLIT_DEADLINE", "FRACTIONAL_POLICY", "CONFIDENCE",
    "SOURCE", "KEY", "STATUS",
]
# New 12-column header (post-Phase 5b).
_NEW_HEADER = [*_LEGACY_HEADER, "SIGNAL_TYPE"]

_LEGACY_ROW = [
    "2026-05-01", "ACME", "buy", "1-for-40", "2026-06-01",
    "May 29 by 4pm (Eastern Time)", "ROUND_UP", "0.93",
    "SEC_EFTS", "K-ACME", "PENDING",
]


def _hit(acc: str, ticker: str | None, title: str) -> Hit:
    return Hit(
        accession=acc, cik="1234567", ticker=ticker, form="8-K",
        filing_date="2026-05-01", title=title,
        link=f"https://sec.gov/{acc}",
    )


# --- backward compatibility ------------------------------------------

def test_legacy_11_column_sheet_defaults_to_round_up_reverse():
    """The pre-Phase 5b Apps Script writes 11 columns. Existing rows
    must parse cleanly with SIGNAL_TYPE defaulted, not crash and not
    silently lose the per-row metadata."""
    sigs = parse_values([_LEGACY_HEADER, _LEGACY_ROW])
    assert len(sigs) == 1
    assert sigs[0].signal_type == SIGNAL_TYPE_ROUND_UP_REVERSE
    assert sigs[0].ticker == "ACME"


def test_new_12_column_sheet_carries_signal_type():
    new_row = [*_LEGACY_ROW, "SPIN_OFF"]
    sigs = parse_values([_NEW_HEADER, new_row])
    assert sigs[0].signal_type == "SPIN_OFF"


def test_signal_type_is_uppercased_for_consistency():
    new_row = [*_LEGACY_ROW, "special_div"]
    sigs = parse_values([_NEW_HEADER, new_row])
    assert sigs[0].signal_type == "SPECIAL_DIV"


def test_blank_signal_type_falls_back_to_round_up_reverse():
    new_row = [*_LEGACY_ROW, ""]
    sigs = parse_values([_NEW_HEADER, new_row])
    assert sigs[0].signal_type == SIGNAL_TYPE_ROUND_UP_REVERSE


def test_signal_named_tuple_default_when_constructed_directly():
    s = Signal(
        created_at="", ticker="ACME", action="buy", ratio="",
        effective_date="", presplit_deadline="", fractional_policy="",
        confidence="", source="", key="K-ACME", status="",
    )
    assert s.signal_type == SIGNAL_TYPE_ROUND_UP_REVERSE


# --- producer fan-out -------------------------------------------------

def test_to_gui_rows_emits_signal_type_as_12th_column():
    p = producer.Play(
        ticker="ACME", ratio="1-for-40", effective_date="June 1, 2026",
        fractional_policy="ROUND_UP", confidence=0.93,
        expectation="ROUND_UP_CONFIRMED", source="SEC_EFTS",
        key="K", split_key="SK", link="https://sec.gov/x",
        signal_type=SIGNAL_TYPE_SPIN_OFF,
    )
    (row,) = producer.to_gui_rows([p])
    assert row[-1] == SIGNAL_TYPE_SPIN_OFF
    assert len(row) == len(producer.GUI_QUEUE_HEADER)


def test_discover_emits_spin_off_signal_when_classifier_matches(monkeypatch):
    """End-to-end: spin-off EFTS hits → parse_spin_off matches →
    Play with signal_type=SPIN_OFF."""
    spin_text = (
        "On May 1, 2026, the Board of Directors approved the "
        "spin-off of Subsidiary. The record date is June 15, 2026 "
        "and one share of Subsidiary common stock will be distributed "
        "for every 4 shares of Parent common stock held by holders "
        "of record."
    )

    def _fake_efts(q, *a, **k):
        if "spin-off" in q or "spinoff" in q:
            return [_hit("SPIN-1", "PRNT", "Spin-off announcement")]
        return []

    monkeypatch.setattr(producer, "efts_search", _fake_efts)
    monkeypatch.setattr(producer, "fetch_filing_text", lambda _u: spin_text)
    monkeypatch.setattr(producer, "cik_to_ticker", lambda _c: None)
    plays = producer.discover(
        window_days=7,
        include_spin_off=True,
        include_special_div=False,
    )
    assert any(p.signal_type == SIGNAL_TYPE_SPIN_OFF for p in plays)
    spin = next(p for p in plays if p.signal_type == SIGNAL_TYPE_SPIN_OFF)
    assert spin.ticker == "PRNT"
    assert spin.ratio == "1-for-4"


def test_discover_emits_special_div_signal_when_classifier_matches(
    monkeypatch,
):
    div_text = (
        "The Board of Directors today declared a special cash dividend "
        "of $3.00 per share, payable on June 30, 2026, to stockholders "
        "of record as of June 15, 2026."
    )

    def _fake_efts(q, *a, **k):
        if "special" in q or "extraordinary" in q:
            return [_hit("DIV-1", "DIVCO", "Special dividend declared")]
        return []

    monkeypatch.setattr(producer, "efts_search", _fake_efts)
    monkeypatch.setattr(producer, "fetch_filing_text", lambda _u: div_text)
    monkeypatch.setattr(producer, "cik_to_ticker", lambda _c: None)
    plays = producer.discover(
        window_days=7,
        include_spin_off=False,
        include_special_div=True,
    )
    assert any(p.signal_type == SIGNAL_TYPE_SPECIAL_DIV for p in plays)
    div = next(p for p in plays if p.signal_type == SIGNAL_TYPE_SPECIAL_DIV)
    assert div.ticker == "DIVCO"
    assert "3" in div.ratio  # amount carried in the ratio field for display


def test_discover_can_disable_new_types(monkeypatch):
    """include_spin_off=False / include_special_div=False short-circuit
    those discovery passes so the existing reverse-split flow runs
    identically to pre-Phase-5b code."""
    monkeypatch.setattr(producer, "efts_search", lambda *a, **k: [])
    monkeypatch.setattr(producer, "fetch_filing_text", lambda _u: "")
    monkeypatch.setattr(producer, "cik_to_ticker", lambda _c: None)
    plays = producer.discover(
        window_days=7,
        include_spin_off=False,
        include_special_div=False,
    )
    assert plays == []


def test_economic_dedupe_segregates_signal_types(monkeypatch):
    """A reverse-split and a spin-off for the same ticker on the same
    date must NOT collide in the seen_econ set — different prefixes
    keep them as distinct economic events."""
    from src.edgar.keys import spin_off_key, split_key
    rs_sk = split_key("ACME", "1-for-40", "2026-06-01", "ROUND_UP")
    so_sk = spin_off_key("ACME", "2026-06-01", "1-for-4")
    assert rs_sk != so_sk
    assert "SPIN_OFF" in so_sk
    assert "SPIN_OFF" not in rs_sk
