"""CLI: ``python -m src.autosell`` — list due sells and notify.

Designed to run from launchd once a day. Side effects:

1. Print the summary line + the table to stdout (captured to the
   per-job log file by the launchd plist).
2. If ``RSA_NOTIFY_WEBHOOK`` is set and the count is non-zero,
   POST a one-line summary to that Discord-compatible webhook so
   the operator gets a phone notification.

This CLI **never** places orders. Sell execution is operator-driven
via the GUI's auto-sell review pane.

Exit codes:
    0 — ran successfully (regardless of whether anything was due).
    1 — operational error (e.g. ledger DB unreadable).
"""

from __future__ import annotations

import os
import sys

from src.autosell.finder import find_due_sells, summary_text


def _post_webhook(url: str, text: str) -> None:
    if not url.strip():
        return
    try:
        import requests  # noqa: PLC0415

        requests.post(url, json={"content": text}, timeout=10)
    except Exception as exc:
        # Notification is best-effort; don't fail the job on a webhook error.
        print(f"(webhook post failed: {exc})", file=sys.stderr)


def main() -> int:
    """Print due-sell summary; ping webhook on non-zero. Return exit code."""
    try:
        due = find_due_sells()
    except Exception as exc:
        print(f"AutoRSA auto-sell finder failed: {exc}", file=sys.stderr)
        return 1
    line = summary_text(due)
    print(line)
    if due:
        # Tabular detail for log readers.
        print()
        print(
            f"{'broker':<14} {'account':<14} {'ticker':<8} "
            f"{'qty':>6} {'type':<18} hold_until",
        )
        for d in due:
            print(
                f"{d.broker:<14} {d.account:<14} {d.ticker:<8} "
                f"{d.qty:>6.0f} {d.signal_type:<18} {d.hold_until}",
            )
        _post_webhook(os.getenv("RSA_NOTIFY_WEBHOOK", ""), line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
