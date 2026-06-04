"""Turn ingested GUI_QUEUE signals into an actionable execution plan.

Pure and decoupled (the ledger check is injected) so it's unit-tested
without a DB. Quantity is always exactly 1 (decided at execution).

Phase 7: per-signal-type gating. The cascade now branches on
``Signal.signal_type``:

* ``ROUND_UP_REVERSE`` — original behavior: requires a confident
  ROUND_UP fractional policy.
* ``SPIN_OFF`` — requires confidence ≥ ``_NEW_TYPE_MIN_CONF`` (0.75).
* ``SPECIAL_DIV`` — same threshold plus a positive dollar amount
  parsed from the ratio field (e.g. ``$2.50``).

The operator opts into which types are actionable via the
``enabled_signal_types`` parameter (sourced from the vault setting
``RSA_SIGNAL_TYPES_ENABLED``). Default: only ``ROUND_UP_REVERSE``,
so the existing flow is unchanged until the operator explicitly
turns on the new types.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, NamedTuple
from zoneinfo import ZoneInfo

from src.edgar.classify import (
    SIGNAL_TYPE_ROUND_UP_REVERSE,
    SIGNAL_TYPE_SPECIAL_DIV,
    SIGNAL_TYPE_SPIN_OFF,
    is_round_up_fractional,
)
from src.edgar.keys import (
    special_dividend_key,
    spin_off_key,
)
from src.edgar.keys import (
    split_key as make_split_key,
)
from src.edgar.market_calendar import parse_effective_date

# Effective dates in GUI_QUEUE are NYSE-relative (the split is a
# NYSE event). Comparing them against the system-local date means a
# Mac Mini in PT can still consider an ET-effective-today split as
# "today" at 9pm PT (midnight ET), and at midnight PT it correctly
# reads as past. Use ET so the gate matches the event's reality.
_NYSE_TZ = ZoneInfo("America/New_York")

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.gui.core.sheets import Signal

DECISION_ACTIONABLE = "ACTIONABLE"
DECISION_SKIP = "SKIP"

# Confidence floor for the new signal types. Conservative (matches
# the producer's discovery gate) — false positives on a spin-off /
# special-div are more costly than a missed alert.
_NEW_TYPE_MIN_CONF = 0.75

# Default allow-list: only the original reverse-split flow. Operator
# opts in to the new types via the vault setting RSA_SIGNAL_TYPES_ENABLED
# (comma-separated). When that env var is absent we use this default.
DEFAULT_ENABLED_TYPES: frozenset[str] = frozenset({SIGNAL_TYPE_ROUND_UP_REVERSE})

# How many calendar days after the event the position can be sold.
# Spin-offs typically settle within ~5 trading days of the
# distribution date. Special-divs are claim-on-record-date and the
# share can be sold any time after the ex-date — 1 day is a safe
# buffer for the EX adjustment to land in account history.
_HOLD_DAYS_SPIN_OFF = 5
_HOLD_DAYS_SPECIAL_DIV = 1

# Parses a $X.XX or $X amount from the producer's `ratio` field
# for SPECIAL_DIV plays.
_DOLLAR_AMOUNT_RX = re.compile(r"\$\s?(\d+(?:\.\d{1,4})?)")


class PlanItem(NamedTuple):
    """One planned (or skipped) signal with the reason.

    Phase 7 fields:

    * ``signal_type`` carries the originating type (ROUND_UP_REVERSE /
      SPIN_OFF / SPECIAL_DIV) so downstream renderers and the
      ledger can group by it.
    * ``hold_until`` is the ISO date on/after which the auto-sell
      job (Phase 8) may sell this position. Empty for the round-up
      flow (manual sell only) and for SKIP decisions.
    """

    ticker: str
    key: str
    split_key: str
    ratio: str
    effective_date: str
    fractional_policy: str
    confidence: float
    decision: str
    reason: str
    signal_type: str = SIGNAL_TYPE_ROUND_UP_REVERSE
    hold_until: str = ""


def _conf(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _dollar_amount(ratio: str) -> float:
    m = _DOLLAR_AMOUNT_RX.search(str(ratio or ""))
    if not m:
        return 0.0
    try:
        return float(m.group(1))
    except ValueError:
        return 0.0


def _split_key_for(signal: Signal) -> str:
    """Pick the right dedupe key for the signal's type."""
    # Normalize: callers/tests may pass a lower-case signal_type. Without
    # this, a "spin_off" signal fell through to the round-up key, so the
    # ledger's economic dedupe wouldn't recognize it and the same play
    # could be bought twice (or wrongly deduped against a round-up).
    st = (signal.signal_type or "").upper()
    if st == SIGNAL_TYPE_SPIN_OFF:
        return spin_off_key(signal.ticker, signal.effective_date, signal.ratio)
    if st == SIGNAL_TYPE_SPECIAL_DIV:
        return special_dividend_key(
            signal.ticker, signal.effective_date, _dollar_amount(signal.ratio),
        )
    return make_split_key(
        signal.ticker, signal.ratio,
        signal.effective_date, signal.fractional_policy,
    )


def _hold_until_for(signal: Signal, eff: date | None) -> str:
    """Compute the auto-sell date for the signal type, or '' for manual."""
    if eff is None:
        return ""
    if signal.signal_type == SIGNAL_TYPE_SPIN_OFF:
        return (eff + timedelta(days=_HOLD_DAYS_SPIN_OFF)).isoformat()
    if signal.signal_type == SIGNAL_TYPE_SPECIAL_DIV:
        return (eff + timedelta(days=_HOLD_DAYS_SPECIAL_DIV)).isoformat()
    return ""


def _classify_round_up(  # noqa: PLR0913
    s: Signal, *, conf: float, sk: str, eff: date | None, today: date,
    is_done: Callable[[str], bool],
) -> tuple[str, str]:
    if eff is not None and eff < today:
        return DECISION_SKIP, f"past effective date ({eff.isoformat()})"
    if s.action.lower() != "buy":
        return DECISION_SKIP, f"action is {s.action!r}, not buy"
    if not is_round_up_fractional(s.fractional_policy, conf):
        return (
            DECISION_SKIP,
            f"not a confident ROUND_UP "
            f"({s.fractional_policy or 'UNSPECIFIED'} @ {conf:.2f})",
        )
    if sk and is_done(sk):
        return DECISION_SKIP, "already executed (ledger)"
    return DECISION_ACTIONABLE, "confirmed ROUND_UP"


def _classify_spin_off(  # noqa: PLR0913
    s: Signal, *, conf: float, sk: str, eff: date | None, today: date,
    is_done: Callable[[str], bool],
) -> tuple[str, str]:
    if eff is not None and eff < today:
        return DECISION_SKIP, f"past record date ({eff.isoformat()})"
    if s.action.lower() != "buy":
        return DECISION_SKIP, f"action is {s.action!r}, not buy"
    if conf < _NEW_TYPE_MIN_CONF:
        return (
            DECISION_SKIP,
            f"spin-off confidence {conf:.2f} below floor "
            f"{_NEW_TYPE_MIN_CONF}",
        )
    if sk and is_done(sk):
        return DECISION_SKIP, "already executed (ledger)"
    return DECISION_ACTIONABLE, "confirmed SPIN_OFF"


def _classify_special_div(  # noqa: PLR0913
    s: Signal, *, conf: float, sk: str, eff: date | None, today: date,
    is_done: Callable[[str], bool],
) -> tuple[str, str]:
    if eff is not None and eff < today:
        return DECISION_SKIP, f"past record date ({eff.isoformat()})"
    if s.action.lower() != "buy":
        return DECISION_SKIP, f"action is {s.action!r}, not buy"
    if conf < _NEW_TYPE_MIN_CONF:
        return (
            DECISION_SKIP,
            f"special-div confidence {conf:.2f} below floor "
            f"{_NEW_TYPE_MIN_CONF}",
        )
    if _dollar_amount(s.ratio) <= 0:
        return DECISION_SKIP, "special-div has no positive $ amount"
    if sk and is_done(sk):
        return DECISION_SKIP, "already executed (ledger)"
    return DECISION_ACTIONABLE, "confirmed SPECIAL_DIV"


def plan_signals(
    signals: list[Signal],
    *,
    is_done: Callable[[str], bool],
    today: date | None = None,
    enabled_signal_types: frozenset[str] | None = None,
) -> list[PlanItem]:
    """Classify each signal as ACTIONABLE or SKIP (with a reason).

    ``is_done(split_key)`` reports whether the economic split was
    already executed/in-flight anywhere (ledger.economic_done).
    ``today`` defaults to the current NYSE-zone date.
    ``enabled_signal_types`` defaults to ``DEFAULT_ENABLED_TYPES``
    (round-ups only); supply a different frozenset to opt into
    SPIN_OFF / SPECIAL_DIV — typically sourced from the vault
    setting ``RSA_SIGNAL_TYPES_ENABLED``.
    """
    today = today or datetime.now(_NYSE_TZ).date()
    enabled = enabled_signal_types or DEFAULT_ENABLED_TYPES
    out: list[PlanItem] = []
    for s in signals:
        conf = _conf(s.confidence)
        sig_type = (s.signal_type or SIGNAL_TYPE_ROUND_UP_REVERSE).upper()
        sk = _split_key_for(s)
        eff = parse_effective_date(s.effective_date)

        if sig_type not in enabled:
            decision, reason = (
                DECISION_SKIP,
                f"{sig_type} not in enabled signal types",
            )
        elif sig_type == SIGNAL_TYPE_SPIN_OFF:
            decision, reason = _classify_spin_off(
                s, conf=conf, sk=sk, eff=eff, today=today, is_done=is_done,
            )
        elif sig_type == SIGNAL_TYPE_SPECIAL_DIV:
            decision, reason = _classify_special_div(
                s, conf=conf, sk=sk, eff=eff, today=today, is_done=is_done,
            )
        else:
            decision, reason = _classify_round_up(
                s, conf=conf, sk=sk, eff=eff, today=today, is_done=is_done,
            )

        hold_until = (
            _hold_until_for(s, eff)
            if decision == DECISION_ACTIONABLE
            else ""
        )

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
                signal_type=sig_type,
                hold_until=hold_until,
            ),
        )
    return out
