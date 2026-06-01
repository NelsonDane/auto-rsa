"""Group ledger rows by signal_type and compute honest metrics.

All counts are direct from the ledger (real). The "estimated
profit" column is `fills x operator_avg_profit_per_fill` -- the
operator sets the per-type average via vault settings. This
deliberately keeps the dashboard simple: real per-fill P&L would
need price capture per broker per day, which is a separate build.
"""

from __future__ import annotations

from typing import NamedTuple

from src.edgar.classify import (
    SIGNAL_TYPE_ROUND_UP_REVERSE,
    SIGNAL_TYPE_SPECIAL_DIV,
    SIGNAL_TYPE_SPIN_OFF,
)

# Default avg profit per fill, in USD. Operator overrides via vault
# settings RSA_AVG_PROFIT_<TYPE>. These numbers are pessimistic
# placeholders meant to be replaced with real-world observation.
DEFAULT_AVG_PROFIT_PER_FILL: dict[str, float] = {
    SIGNAL_TYPE_ROUND_UP_REVERSE: 3.50,
    SIGNAL_TYPE_SPIN_OFF: 5.00,
    SIGNAL_TYPE_SPECIAL_DIV: 10.00,
}


class SignalTypeMetrics(NamedTuple):
    """One row in the per-signal-type dashboard."""

    signal_type: str
    # Counts (all sourced from the ledger — real).
    distinct_alerts: int  # unique play_keys seen
    intended: int  # status=INTENDED (in-flight buys)
    bought: int  # status=EXECUTED action=buy
    sold: int  # status=EXECUTED action=sell
    failed: int  # status=FAILED (any action)
    # Derived ratios (real).
    completion_rate: float  # sold / bought, 0 if bought==0
    # Operator-estimated profit (clearly labeled as estimate in UI).
    avg_profit_per_fill_usd: float
    estimated_profit_usd: float


def _bucket(rows: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    """Group ledger rows by signal_type (default ROUND_UP_REVERSE)."""
    out: dict[str, list[dict[str, object]]] = {}
    for r in rows:
        st = str(r.get("signal_type") or SIGNAL_TYPE_ROUND_UP_REVERSE).upper()
        out.setdefault(st, []).append(r)
    return out


def aggregate_by_signal_type(
    rows: list[dict[str, object]],
    *,
    avg_profit_overrides: dict[str, float] | None = None,
) -> list[SignalTypeMetrics]:
    """Bucket ledger rows by signal_type, return one row per type.

    The result is ordered by ``SignalTypeMetrics.distinct_alerts``
    descending so the most-active types appear first. Always returns
    a row for each known type (zero counts when no activity) so the
    dashboard table has consistent shape across runs.
    """
    overrides = avg_profit_overrides or {}
    buckets = _bucket(rows)
    known = (
        SIGNAL_TYPE_ROUND_UP_REVERSE,
        SIGNAL_TYPE_SPIN_OFF,
        SIGNAL_TYPE_SPECIAL_DIV,
    )
    out: list[SignalTypeMetrics] = []
    for st in known:
        bkt = buckets.get(st, [])
        distinct = len({str(r.get("key", "")) for r in bkt if r.get("key")})
        intended = sum(1 for r in bkt if r.get("status") == "INTENDED")
        bought = sum(
            1 for r in bkt
            if r.get("status") == "EXECUTED" and str(r.get("action", "")).lower() == "buy"
        )
        sold = sum(
            1 for r in bkt
            if r.get("status") == "EXECUTED" and str(r.get("action", "")).lower() == "sell"
        )
        failed = sum(1 for r in bkt if r.get("status") == "FAILED")

        avg_profit = float(
            overrides.get(st, DEFAULT_AVG_PROFIT_PER_FILL.get(st, 0.0)),
        )
        completion = (sold / bought) if bought else 0.0
        out.append(
            SignalTypeMetrics(
                signal_type=st,
                distinct_alerts=distinct,
                intended=intended,
                bought=bought,
                sold=sold,
                failed=failed,
                completion_rate=completion,
                avg_profit_per_fill_usd=avg_profit,
                estimated_profit_usd=bought * avg_profit,
            ),
        )
    out.sort(key=lambda m: m.distinct_alerts, reverse=True)
    return out


def vault_setting_key(signal_type: str) -> str:
    """Return the vault setting name for the operator's avg-profit override."""
    return f"RSA_AVG_PROFIT_{signal_type.upper()}"


def overrides_from_settings(
    settings: dict[str, str],
) -> dict[str, float]:
    """Pull RSA_AVG_PROFIT_<TYPE> overrides from a vault settings dict."""
    out: dict[str, float] = {}
    for st in DEFAULT_AVG_PROFIT_PER_FILL:
        raw = settings.get(vault_setting_key(st), "").strip()
        if not raw:
            continue
        try:
            out[st] = float(raw)
        except ValueError:
            continue
    return out
