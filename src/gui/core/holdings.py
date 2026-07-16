"""Structured holdings snapshot: parse, store, aggregate.

The engine emits one ``HOLDINGS_SENTINEL`` line per position during a
holdings pull; the runner parses them (:func:`parse_line`) and persists
them (:func:`save_positions`). The Balances tab renders the stored
snapshot as a real table, and reconciliation compares it to the ledger.

The snapshot is merged *per broker*: pulling one broker's holdings
replaces only that broker's rows and stamps its capture time, so a
single-broker pull never wipes the others. Everything is best-effort and
never raises.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
HOLDINGS_PATH = _PROJECT_ROOT / "creds" / "holdings_snapshot.json"
_FIELDS = 7
# Synthetic "stock" the engine emits carrying an account's TOTAL value, so
# the GUI can derive cash = total - sum(position values). Filtered out of
# the ticker table; consumed by the per-account/per-broker cash view.
ACCOUNT_TOTAL_MARKER = "__ACCOUNT_TOTAL__"


def _is_account_total(p: dict) -> bool:
    return str(p.get("stock", "")).upper() == ACCOUNT_TOTAL_MARKER


def real_positions(positions: list[dict]) -> list[dict]:
    """Positions minus the synthetic account-total marker rows."""
    return [p for p in positions if not _is_account_total(p)]


def _empty() -> dict:
    return {"positions": [], "captured_at": {}}


def parse_line(payload: str) -> dict | None:
    """Parse a HOLDINGS_SENTINEL payload (7 tab-separated fields) to a dict.

    Returns None on any malformed line so one bad row can't break capture.
    """
    parts = payload.split("\t")
    if len(parts) != _FIELDS:
        return None
    broker, parent, account, stock, qty_s, price_s, total_s = (
        p.strip() for p in parts
    )
    if not broker or not stock:
        return None
    try:
        quantity = float(qty_s)
        price = float(price_s)
        total = float(total_s)
    except (TypeError, ValueError):
        return None
    return {
        "broker": broker,
        "parent": parent,
        "account": account,
        "stock": stock.upper(),
        "quantity": quantity,
        "price": price,
        "total": total,
    }


def _read() -> dict:
    try:
        data = json.loads(HOLDINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    data.setdefault("positions", [])
    data.setdefault("captured_at", {})
    if not isinstance(data["positions"], list):
        data["positions"] = []
    if not isinstance(data["captured_at"], dict):
        data["captured_at"] = {}
    return data


def _write(data: dict) -> None:
    with contextlib.suppress(OSError):
        HOLDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = HOLDINGS_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(HOLDINGS_PATH)


def save_positions(positions: list[dict], *, captured_at: str) -> None:
    """Merge ``positions`` into the stored snapshot.

    Replaces the stored rows for every broker present in ``positions``
    (so a single-broker pull updates only that broker), keeps the rest,
    and stamps each updated broker's capture time. No-op on an empty list
    so a run that captured nothing never wipes a good snapshot.
    """
    if not positions:
        return
    data = _read()
    brokers = {p["broker"] for p in positions if p.get("broker")}
    kept = [p for p in data["positions"] if p.get("broker") not in brokers]
    data["positions"] = kept + list(positions)
    for b in brokers:
        data["captured_at"][b] = captured_at
    _write(data)


def load_snapshot() -> dict:
    """Return the stored snapshot: ``{"positions": [...], "captured_at": {...}}``."""
    return _read()


def clear_snapshot() -> None:
    """Delete the stored holdings snapshot (best-effort)."""
    with contextlib.suppress(OSError):
        HOLDINGS_PATH.unlink()


def aggregate_by_ticker(positions: list[dict]) -> list[dict]:
    """Sum quantity + value per ticker across accounts/brokers.

    Returns rows ``{stock, quantity, value, brokers}`` sorted by value
    descending (largest positions first).
    """
    agg: dict[str, dict] = {}
    for p in real_positions(positions):
        stock = str(p.get("stock", "")).upper()
        if not stock:
            continue
        row = agg.setdefault(
            stock, {"quantity": 0.0, "value": 0.0, "brokers": set()},
        )
        with contextlib.suppress(TypeError, ValueError):
            row["quantity"] += float(p.get("quantity", 0) or 0)
        with contextlib.suppress(TypeError, ValueError):
            row["value"] += float(p.get("total", 0) or 0)
        if p.get("broker"):
            row["brokers"].add(p["broker"])
    out = [
        {
            "stock": stock,
            "quantity": round(row["quantity"], 4),
            "value": round(row["value"], 2),
            "brokers": len(row["brokers"]),
        }
        for stock, row in agg.items()
    ]
    out.sort(key=lambda r: r["value"], reverse=True)
    return out


def _f(v: object) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def aggregate_by_broker(positions: list[dict]) -> list[dict]:
    """Group holdings into per-broker sections with derived cash.

    For each broker returns::

        {broker, cash, stocks_value, total, accounts: [
            {parent, account, cash, stocks_value, total, holdings: [...]},
        ]}

    ``stocks_value`` = sum of position values; ``total`` = sum of the
    account totals the engine emitted; ``cash`` = total - stocks_value
    (never negative). Accounts and brokers are sorted by total value desc.
    """
    # (broker, parent, account) -> {stocks_value, total, holdings}
    accounts: dict[tuple, dict] = {}

    def _acct(p: dict) -> dict:
        keyt = (p.get("broker", ""), p.get("parent", ""), p.get("account", ""))
        return accounts.setdefault(
            keyt, {"stocks_value": 0.0, "total": None, "holdings": []},
        )

    for p in positions:
        entry = _acct(p)
        if _is_account_total(p):
            entry["total"] = _f(p.get("total"))
            continue
        val = _f(p.get("total"))
        entry["stocks_value"] += val
        entry["holdings"].append(
            {
                "stock": str(p.get("stock", "")).upper(),
                "quantity": round(_f(p.get("quantity")), 4),
                "price": round(_f(p.get("price")), 2),
                "value": round(val, 2),
            },
        )

    by_broker: dict[str, dict] = {}
    for (broker, parent, account), e in accounts.items():
        stocks_value = round(e["stocks_value"], 2)
        # If the broker never emitted an account total, fall back to the
        # stocks value (cash unknown -> 0) so figures still add up.
        total = round(e["total"] if e["total"] is not None else stocks_value, 2)
        cash = round(max(0.0, total - stocks_value), 2)
        b = by_broker.setdefault(
            broker, {"broker": broker, "cash": 0.0, "stocks_value": 0.0,
                     "total": 0.0, "accounts": []},
        )
        b["cash"] = round(b["cash"] + cash, 2)
        b["stocks_value"] = round(b["stocks_value"] + stocks_value, 2)
        b["total"] = round(b["total"] + total, 2)
        b["accounts"].append(
            {
                "parent": parent,
                "account": account,
                "cash": cash,
                "stocks_value": stocks_value,
                "total": total,
                "holdings": sorted(
                    e["holdings"], key=lambda h: h["value"], reverse=True,
                ),
            },
        )

    out = list(by_broker.values())
    for b in out:
        b["accounts"].sort(key=lambda a: a["total"], reverse=True)
    out.sort(key=lambda b: b["total"], reverse=True)
    return out


def totals(positions: list[dict]) -> dict:
    """Portfolio-wide ``{cash, stocks_value, total}`` (cash derived)."""
    brokers = aggregate_by_broker(positions)
    cash = round(sum(b["cash"] for b in brokers), 2)
    stocks_value = round(sum(b["stocks_value"] for b in brokers), 2)
    return {
        "cash": cash,
        "stocks_value": stocks_value,
        "total": round(cash + stocks_value, 2),
    }
