"""Signal -> execution plan gating (pure)."""

from datetime import date

from src.gui.core.sheets import Signal
from src.gui.core.signal_plan import (
    DECISION_ACTIONABLE,
    DECISION_SKIP,
    DEFAULT_ENABLED_TYPES,
    plan_signals,
)

_ALL_TYPES = frozenset({"ROUND_UP_REVERSE", "SPIN_OFF", "SPECIAL_DIV"})


def _sig(ticker, policy, conf, *, action="buy", ratio="1-for-40",
         eff="June 1, 2026", key=None, signal_type="ROUND_UP_REVERSE"):
    return Signal(
        created_at="2026-05-17",
        ticker=ticker,
        action=action,
        ratio=ratio,
        effective_date=eff,
        presplit_deadline="",
        fractional_policy=policy,
        confidence=str(conf),
        source="SEC_EFTS",
        key=key or f"K-{ticker}",
        status="PENDING",
        signal_type=signal_type,
    )


def test_actionable_round_up():
    sigs = [_sig("ACME", "ROUND_UP", 0.93)]
    (item,) = plan_signals(
        sigs, is_done=lambda _sk: False, today=date(2026, 5, 26),
    )
    assert item.decision == DECISION_ACTIONABLE
    assert item.ticker == "ACME"
    assert item.split_key == "ACME|1-FOR-40|JUNE 1, 2026|ROUND_UP"


def test_skips_non_round_up_and_low_conf_and_sell():
    sigs = [
        _sig("CASHCO", "CASH_IN_LIEU", 0.96),
        _sig("LOWCO", "ROUND_UP", 0.40),          # below 0.60 buy gate
        _sig("DOWNCO", "ROUND_DOWN", 0.92),
        _sig("SELLCO", "ROUND_UP", 0.93, action="sell"),
        _sig("UNSPEC", "UNSPECIFIED", 0.20),
    ]
    plan = plan_signals(
        sigs, is_done=lambda _sk: False, today=date(2026, 5, 26),
    )
    assert {p.ticker: p.decision for p in plan} == {
        "CASHCO": DECISION_SKIP,
        "LOWCO": DECISION_SKIP,
        "DOWNCO": DECISION_SKIP,
        "SELLCO": DECISION_SKIP,
        "UNSPEC": DECISION_SKIP,
    }
    assert all(p.reason for p in plan)


def test_skips_when_ledger_says_done():
    sigs = [_sig("DONE", "ROUND_UP", 0.93)]
    (item,) = plan_signals(
        sigs, is_done=lambda sk: sk.startswith("DONE|"),
        today=date(2026, 5, 26),
    )
    assert item.decision == DECISION_SKIP
    assert "already executed" in item.reason


def test_bad_confidence_string_is_safe():
    sigs = [_sig("BADCONF", "ROUND_UP", "n/a")]
    (item,) = plan_signals(
        sigs, is_done=lambda _sk: False, today=date(2026, 5, 26),
    )
    assert item.decision == DECISION_SKIP
    assert item.confidence == 0.0


def test_skips_when_effective_date_in_past():
    sigs = [
        _sig("OLDCO", "ROUND_UP", 0.95, eff="2025-01-15"),
        _sig("FUTCO", "ROUND_UP", 0.95, eff="2099-01-15"),
    ]
    plan = plan_signals(
        sigs, is_done=lambda _sk: False, today=date(2026, 5, 26),
    )
    by_ticker = {p.ticker: p for p in plan}
    assert by_ticker["OLDCO"].decision == DECISION_SKIP
    assert "past effective date" in by_ticker["OLDCO"].reason
    assert by_ticker["FUTCO"].decision == DECISION_ACTIONABLE


def test_past_date_wins_even_when_already_done():
    sigs = [_sig("BOTH", "ROUND_UP", 0.95, eff="2025-01-15")]
    (item,) = plan_signals(
        sigs, is_done=lambda _sk: True, today=date(2026, 5, 26),
    )
    assert item.decision == DECISION_SKIP
    assert "past effective date" in item.reason


def test_unparseable_effective_date_is_not_treated_as_past():
    sigs = [_sig("WEIRD", "ROUND_UP", 0.95, eff="when convenient")]
    (item,) = plan_signals(
        sigs, is_done=lambda _sk: False, today=date(2026, 5, 26),
    )
    assert item.decision == DECISION_ACTIONABLE


# --- Phase 7: per-signal-type allow-list ------------------------------

def test_default_allow_list_is_round_up_only():
    assert DEFAULT_ENABLED_TYPES == frozenset({"ROUND_UP_REVERSE"})


def test_spin_off_skipped_when_not_in_default_allow_list():
    """The new types are detected by the producer (Phase 5) but must
    NOT be auto-actioned until the operator opts in. This is the
    safety property the whole gating layer exists to provide."""
    sigs = [_sig(
        "PRNT", policy="", conf=0.85, eff="June 1, 2026",
        signal_type="SPIN_OFF",
    )]
    (item,) = plan_signals(
        sigs, is_done=lambda _sk: False, today=date(2026, 5, 26),
    )
    assert item.decision == DECISION_SKIP
    assert "SPIN_OFF not in enabled" in item.reason


def test_spin_off_actionable_when_enabled_and_above_floor():
    sigs = [_sig(
        "PRNT", policy="", conf=0.85, eff="June 1, 2026",
        ratio="1-for-4", signal_type="SPIN_OFF",
    )]
    (item,) = plan_signals(
        sigs, is_done=lambda _sk: False,
        today=date(2026, 5, 26), enabled_signal_types=_ALL_TYPES,
    )
    assert item.decision == DECISION_ACTIONABLE
    assert item.signal_type == "SPIN_OFF"
    # Hold until ~5 days post record date.
    assert item.hold_until == "2026-06-06"


def test_spin_off_below_floor_is_skipped_even_when_enabled():
    sigs = [_sig(
        "PRNT", policy="", conf=0.70, eff="June 1, 2026",
        signal_type="SPIN_OFF",
    )]
    (item,) = plan_signals(
        sigs, is_done=lambda _sk: False,
        today=date(2026, 5, 26), enabled_signal_types=_ALL_TYPES,
    )
    assert item.decision == DECISION_SKIP
    assert "below floor" in item.reason


def test_special_div_requires_positive_dollar_amount():
    """A SPECIAL_DIV signal whose ratio field has no $ amount should
    skip even when enabled and above the confidence floor — the math
    can't be validated."""
    sigs = [
        _sig("DIVCO", "", 0.90, ratio="", signal_type="SPECIAL_DIV"),
        _sig("OKCO",  "", 0.90, ratio="$1.50",
             signal_type="SPECIAL_DIV", key="K-OK"),
    ]
    plan = plan_signals(
        sigs, is_done=lambda _sk: False,
        today=date(2026, 5, 26), enabled_signal_types=_ALL_TYPES,
    )
    by_ticker = {p.ticker: p for p in plan}
    assert by_ticker["DIVCO"].decision == DECISION_SKIP
    assert "no positive $ amount" in by_ticker["DIVCO"].reason
    assert by_ticker["OKCO"].decision == DECISION_ACTIONABLE
    # Hold until 1 day after the ex/record date.
    assert by_ticker["OKCO"].hold_until == "2026-06-02"


def test_round_up_still_actionable_with_only_round_up_enabled():
    """Smoke test that the existing flow is unchanged by the new
    gating layer when the operator hasn't opted into the new types."""
    sigs = [_sig("ACME", "ROUND_UP", 0.93)]
    (item,) = plan_signals(
        sigs, is_done=lambda _sk: False, today=date(2026, 5, 26),
    )
    assert item.decision == DECISION_ACTIONABLE
    assert item.signal_type == "ROUND_UP_REVERSE"
    # Round-ups never auto-sell (manual only).
    assert item.hold_until == ""
