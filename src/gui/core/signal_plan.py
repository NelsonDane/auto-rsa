"""Turn ingested GUI_QUEUE signals into an actionable execution plan.

Pure and decoupled (the ledger check is injected) so it's unit-tested
without a DB. The bot only ever BUYS confirmed ROUND_UP plays — every
other policy is surfaced but never actioned, mirroring the Apps Script
gate. Quantity is always exactly 1 (decided at execution).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, NamedTuple

from src.edgar.classify import is_round_up_fractional
from src.edgar.keys import split_key as make_split_key
from src.edgar.market_calendar import parse_effective_date

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.gui.core.sheets import Signal

DECISION_ACTIONABLE = "ACTIONABLE"
DECISION_SKIP = "SKIP"


class PlanItem(NamedTuple):
    """One planned (or skipped) signal with the reason."""

    ticker: str
    key: str
    split_key: str
    ratio: str
    effective_date: str
    fractional_policy: str
    confidence: float
    decision: str
    reason: str


def _conf(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def plan_signals(
    signals: list[Signal],
    *,
    is_done: Callable[[str], bool],
    today: date | None = None,
) -> list[PlanItem]:
    """Classify each signal as ACTIONABLE or SKIP (with a reason).

    ``is_done(split_key)`` reports whether the economic split was
    already executed/in-flight anywhere (ledger.economic_done).
    ``today`` defaults to the local date; signals whose effective date
    is strictly before today are skipped (the round has already happened).
    """
    today = today or date.today()  # noqa: DTZ011
    out: list[PlanItem] = []
    for s in signals:
        conf = _conf(s.confidence)
        sk = make_split_key(
            s.ticker, s.ratio, s.effective_date, s.fractional_policy,
        )
        eff = parse_effective_date(s.effective_date)

        if eff is not None and eff < today:
            decision, reason = (
                DECISION_SKIP,
                f"past effective date ({eff.isoformat()})",
            )
        elif s.action.lower() != "buy":
            decision, reason = DECISION_SKIP, f"action is {s.action!r}, not buy"
        elif not is_round_up_fractional(s.fractional_policy, conf):
            decision, reason = (
                DECISION_SKIP,
                f"not a confident ROUND_UP "
                f"({s.fractional_policy or 'UNSPECIFIED'} @ {conf:.2f})",
            )
        elif sk and is_done(sk):
            decision, reason = DECISION_SKIP, "already executed (ledger)"
        else:
            decision, reason = DECISION_ACTIONABLE, "confirmed ROUND_UP"

        out.append(
            PlanItem(
                ticker=s.ticker,
                key=s.key,
                split_key=sk,
                ratio=s.ratio,
                effective_date=s.effective_date,
                fractional_policy=s.fractional_policy,
                confidence=conf,
                decision=decision,
                reason=reason,
            ),
        )
    return out
