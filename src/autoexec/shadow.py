"""Shadow planning — what the unattended executor *would* do.

Pure and side-effect-free: given the ingested signals and the ledger's
economic-dedupe view, produce a per-play report. No broker contact, no
orders, no writes. This is the safe core of M5 phase 1.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, NamedTuple

from src.gui.core.signal_plan import DECISION_ACTIONABLE, plan_signals

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.gui.core.sheets import Signal


class ShadowItem(NamedTuple):
    """One planned/skipped play as it would be handled unattended."""

    ticker: str
    decision: str  # WOULD_BUY | SKIP
    reason: str
    key: str
    split_key: str
    ratio: str
    effective_date: str
    confidence: float
    broker_targets: list[str]


def parse_account_filter(raw: str) -> dict[str, list[str]]:
    """Parse the RSA_ACCOUNT_FILTER JSON (same shape the engine uses)."""
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        val = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(val, dict):
        return {}
    return {str(k): [str(m) for m in (v or [])] for k, v in val.items()}


def build_shadow(
    signals: list[Signal],
    *,
    broker_keys: list[str],
    account_filter: dict[str, list[str]],
    is_done: Callable[[str], bool],
) -> list[ShadowItem]:
    """Return the shadow plan: what would run, and what would be skipped.

    ``broker_keys`` is the unattended allow-list (informational in
    shadow — no broker is contacted). ``account_filter`` annotates how
    many sub-accounts each broker would target.
    """
    items: list[ShadowItem] = []
    for p in plan_signals(signals, is_done=is_done):
        if p.decision == DECISION_ACTIONABLE:
            targets = []
            for b in broker_keys:
                masks = account_filter.get(b)
                if masks is None:
                    targets.append(b)
                elif masks:
                    targets.append(f"{b}({len(masks)} acct)")
                else:
                    targets.append(f"{b}(filter:none)")
            items.append(
                ShadowItem(
                    ticker=p.ticker,
                    decision="WOULD_BUY",
                    reason=p.reason,
                    key=p.key,
                    split_key=p.split_key,
                    ratio=p.ratio,
                    effective_date=p.effective_date,
                    confidence=p.confidence,
                    broker_targets=targets,
                ),
            )
        else:
            items.append(
                ShadowItem(
                    ticker=p.ticker,
                    decision="SKIP",
                    reason=p.reason,
                    key=p.key,
                    split_key=p.split_key,
                    ratio=p.ratio,
                    effective_date=p.effective_date,
                    confidence=p.confidence,
                    broker_targets=[],
                ),
            )
    return items


def render_report(items: list[ShadowItem]) -> str:
    """Human-readable shadow report (also fine for a webhook summary)."""
    would = [i for i in items if i.decision == "WOULD_BUY"]
    skip = [i for i in items if i.decision == "SKIP"]
    lines = [
        f"SHADOW: {len(would)} would-buy, {len(skip)} skipped, "
        f"{len(items)} signals (no orders placed).",
        *(
            f"  WOULD BUY 1 {i.ticker}  {i.ratio}  "
            f"eff={i.effective_date or '?'}  conf={i.confidence:.2f}  "
            f"-> {', '.join(i.broker_targets) or '-'}  [{i.key}]"
            for i in would
        ),
        *(f"  skip {i.ticker}: {i.reason}" for i in skip),
    ]
    return "\n".join(lines)
