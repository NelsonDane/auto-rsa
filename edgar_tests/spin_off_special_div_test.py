"""Spin-off + special-dividend classifier branches."""

from __future__ import annotations

from src.edgar.classify import (
    SIGNAL_TYPE_ROUND_UP_REVERSE,
    SIGNAL_TYPE_SPECIAL_DIV,
    SIGNAL_TYPE_SPIN_OFF,
    SIGNAL_TYPES,
    parse_special_dividend,
    parse_spin_off,
)


# --- spin-off ---------------------------------------------------------

def test_signal_type_constants_present():
    assert SIGNAL_TYPE_ROUND_UP_REVERSE in SIGNAL_TYPES
    assert SIGNAL_TYPE_SPIN_OFF in SIGNAL_TYPES
    assert SIGNAL_TYPE_SPECIAL_DIV in SIGNAL_TYPES


def test_spin_off_strong_with_supporting_matches():
    text = (
        "On May 1, 2026, the Board of Directors authorized the "
        "spin-off of Subsidiary Inc. as a separate publicly-traded "
        "company. The record date for the distribution will be "
        "June 15, 2026, with one share of Subsidiary common stock "
        "distributed for every 3 shares of Parent common stock held."
    )
    r = parse_spin_off(text)
    assert r.matched
    assert r.confidence >= 0.80
    assert r.distribution_ratio == "1-for-3"
    assert "June 15" in r.record_date or "2026" in r.record_date


def test_spin_off_strong_without_supporting_is_low_conf_no_match():
    text = "We have considered a possible spin-off at some point in the future."
    r = parse_spin_off(text)
    assert not r.matched
    assert r.confidence < 0.50


def test_spin_off_extracts_distribution_ratio_only_when_clearly_stated():
    text = (
        "The Board approved a spin-off. Record date: April 1, 2026. "
        "Holders of record will receive one share of NewCo common "
        "stock for every 5 shares of OldCo common stock held."
    )
    r = parse_spin_off(text)
    assert r.matched
    assert r.distribution_ratio == "1-for-5"


def test_spin_off_no_match_on_unrelated_text():
    r = parse_spin_off("This is a stock split announcement, not a spin-off.")
    # No "spin-off" word AND no supporting context → no match.
    assert not r.matched
    assert r.distribution_ratio == ""


def test_spin_off_empty_input_safe():
    r = parse_spin_off("")
    assert not r.matched
    r2 = parse_spin_off(None)  # type: ignore[arg-type]
    assert not r2.matched


# --- special dividend -------------------------------------------------

def test_special_dividend_simple_extraction():
    text = (
        "The Board of Directors today declared a special cash dividend "
        "of $2.50 per share, payable on June 30, 2026, to stockholders "
        "of record as of June 15, 2026."
    )
    r = parse_special_dividend(text)
    assert r.matched
    assert r.amount_per_share == 2.50
    assert "June 15" in r.record_date or "2026" in r.record_date
    assert "June 30" in r.payment_date or "2026" in r.payment_date
    assert r.confidence >= 0.85


def test_special_dividend_extraordinary_phrasing():
    text = (
        "Announced an extraordinary dividend of $0.75 per share. "
        "The ex-dividend date is set for July 1, 2026."
    )
    r = parse_special_dividend(text)
    assert r.matched
    assert r.amount_per_share == 0.75
    assert "July 1" in r.ex_date or "2026" in r.ex_date


def test_quarterly_dividend_alone_is_not_classified():
    text = "The Board declared a regular quarterly cash dividend of $0.25."
    r = parse_special_dividend(text)
    assert not r.matched


def test_special_with_regular_in_same_doc_requires_amount_anchor():
    """Doc mentions BOTH special and quarterly — only matches if
    a $-per-share amount is clearly attached to the special phrase."""
    text_no_amount = (
        "We typically pay a quarterly dividend. Today the Board also "
        "approved a special dividend payment to be detailed later."
    )
    r1 = parse_special_dividend(text_no_amount)
    assert not r1.matched

    text_with_amount = (
        "We typically pay a quarterly dividend. Today the Board also "
        "approved a special cash dividend of $1.00 per share, "
        "payable on July 15, 2026."
    )
    r2 = parse_special_dividend(text_with_amount)
    assert r2.matched
    assert r2.amount_per_share == 1.00


def test_special_dividend_handles_unparseable_amount_gracefully():
    text = (
        "Declared a special cash dividend per share to be determined "
        "at a later date."
    )
    r = parse_special_dividend(text)
    # Strong phrase present but no amount; still matches but lower
    # confidence.
    assert r.matched
    assert r.amount_per_share == 0.0
    assert r.confidence < 0.85


def test_special_dividend_empty_input_safe():
    r = parse_special_dividend("")
    assert not r.matched


def test_special_dividend_evidence_snippet_present():
    text = (
        "Lorem ipsum filler text. The Board approved a special cash "
        "dividend of $1.00 per share payable on July 1, 2026 to "
        "stockholders of record as of June 15, 2026. More filler."
    )
    r = parse_special_dividend(text)
    assert r.matched
    assert "special cash" in r.evidence.lower()
