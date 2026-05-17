"""Signal -> execution plan gating (pure)."""

from src.gui.core.sheets import Signal
from src.gui.core.signal_plan import (
    DECISION_ACTIONABLE,
    DECISION_SKIP,
    plan_signals,
)


def _sig(ticker, policy, conf, *, action="buy", ratio="1-for-40",
         eff="June 1, 2026", key=None):
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
    )


def test_actionable_round_up():
    sigs = [_sig("ACME", "ROUND_UP", 0.93)]
    (item,) = plan_signals(sigs, is_done=lambda _sk: False)
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
    plan = plan_signals(sigs, is_done=lambda _sk: False)
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
    (item,) = plan_signals(sigs, is_done=lambda sk: sk.startswith("DONE|"))
    assert item.decision == DECISION_SKIP
    assert "already executed" in item.reason


def test_bad_confidence_string_is_safe():
    sigs = [_sig("BADCONF", "ROUND_UP", "n/a")]
    (item,) = plan_signals(sigs, is_done=lambda _sk: False)
    assert item.decision == DECISION_SKIP
    assert item.confidence == 0.0
