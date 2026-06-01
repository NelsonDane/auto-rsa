"""Group ledger rows due for sale into a flat, GUI-friendly summary."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import NamedTuple
from zoneinfo import ZoneInfo

from src.ledger import due_for_sell

# Same NYSE-zone semantic as plan_signals — hold_until is computed
# from NYSE record dates, so the "today" we compare against is the
# NYSE date too.
_NYSE_TZ = ZoneInfo("America/New_York")


class DueSell(NamedTuple):
    """One ledger row eligible for sell today."""

    broker: str
    account: str
    ticker: str
    qty: float
    signal_type: str
    hold_until: str
    buy_executed_at: str
    play_key: str
    split_key: str


def _today_nyse_iso() -> str:
    return datetime.now(_NYSE_TZ).date().isoformat()


def find_due_sells(today_iso: str | None = None) -> list[DueSell]:
    """Return positions due for sell as of ``today_iso`` (default: today ET).

    Pure wrapper around :func:`src.ledger.due_for_sell` that shapes
    its dict rows into a typed NamedTuple the GUI can render
    directly. Empty list when nothing is due — render the banner
    as "nothing to sell today" or skip it entirely.
    """
    today = today_iso or _today_nyse_iso()
    rows = due_for_sell(today_iso=today)
    return [
        DueSell(
            broker=str(r["broker"]),
            account=str(r["sub_account"]),
            ticker=str(r["ticker"]),
            qty=float(r["qty"]),
            signal_type=str(r.get("signal_type", "ROUND_UP_REVERSE")),
            hold_until=str(r.get("hold_until", "")),
            buy_executed_at=str(r.get("updated_at", "")),
            play_key=str(r["key"]),
            split_key=str(r.get("split_key", "")),
        )
        for r in rows
    ]


def summary_text(due: list[DueSell]) -> str:
    """Discord-friendly one-liner for the scheduled CLI notifier."""
    if not due:
        return f"AutoRSA: 0 positions due for sell as of {_today_nyse_iso()}."
    by_broker: dict[str, int] = {}
    for d in due:
        by_broker[d.broker] = by_broker.get(d.broker, 0) + 1
    parts = ", ".join(
        f"{b}={n}" for b, n in sorted(by_broker.items())
    )
    return (
        f"AutoRSA: {len(due)} position(s) due for sell "
        f"as of {_today_nyse_iso()} ({parts}). Review in the GUI."
    )


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
