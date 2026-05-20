"""Unattended executor entrypoint — M5 phase 1 (SHADOW ONLY).

    python -m src.autoexec

Reads GUI_QUEUE, prints what it *would* buy, and exits. It places no
orders and contacts no brokers — there is intentionally no --live flag
yet. Config via env (no secrets on argv):

    RSA_SHEETS_SA_JSON    service-account key: inline JSON or @/path
    RSA_SHEETS_ID         spreadsheet ID or URL
    RSA_SHEETS_WORKSHEET  tab (default GUI_QUEUE)
    RSA_AUTO_BROKERS      comma list of allow-listed brokers (or "all")
    RSA_ACCOUNT_FILTER    optional JSON {broker:[mask,...]} for targeting
    RSA_AUTO_DISABLED=1   kill switch (also: creds/AUTOEXEC_DISABLED)
    RSA_AUTO_NOTIFY_URL   optional webhook for the shadow summary
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from src import ledger
from src.autoexec.shadow import build_shadow, parse_account_filter, render_report
from src.gui.core.sheets import SheetsError, fetch_signals

_KILL_FILE = Path(__file__).resolve().parent.parent.parent / "creds" / "AUTOEXEC_DISABLED"


def _load_sa(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("@"):
        return Path(raw[1:]).expanduser().read_text(encoding="utf-8")
    return raw


def _notify(url: str, text: str) -> None:
    if not url:
        return
    try:
        import requests  # noqa: PLC0415

        requests.post(url, json={"content": text[:1900]}, timeout=15)
    except Exception as exc:  # best-effort
        print(f"(notify failed: {exc})", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """Run the shadow plan and report it. Never trades."""
    _ = argv  # no flags in phase 1 by design
    if os.getenv("RSA_AUTO_DISABLED") == "1" or _KILL_FILE.exists():
        print("autoexec disabled (kill switch) — no-op.", file=sys.stderr)
        return 0

    sa = _load_sa(os.getenv("RSA_SHEETS_SA_JSON", ""))
    sheet_id = os.getenv("RSA_SHEETS_ID", "").strip()
    worksheet = os.getenv("RSA_SHEETS_WORKSHEET", "GUI_QUEUE").strip()
    if not sa or not sheet_id:
        print(
            "ERROR: set RSA_SHEETS_SA_JSON and RSA_SHEETS_ID.",
            file=sys.stderr,
        )
        return 2

    raw_brokers = os.getenv("RSA_AUTO_BROKERS", "").strip()
    broker_keys = (
        ["all"]
        if raw_brokers in {"", "all"}
        else [b.strip().lower() for b in raw_brokers.split(",") if b.strip()]
    )
    account_filter = parse_account_filter(os.getenv("RSA_ACCOUNT_FILTER", ""))

    try:
        signals = fetch_signals(sa, sheet_id, worksheet or "GUI_QUEUE")
    except SheetsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3

    items = build_shadow(
        signals,
        broker_keys=broker_keys,
        account_filter=account_filter,
        is_done=ledger.economic_done,
    )
    report = render_report(items)
    print(report)
    _notify(os.getenv("RSA_AUTO_NOTIFY_URL", "").strip(), report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
