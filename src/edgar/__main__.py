"""EDGAR -> GUI_QUEUE producer entrypoint (host-agnostic).

Designed for an always-on host (e.g. a Mac Mini cron / launchd job)
but runs anywhere. Config via env so no secrets are passed on argv:

    RSA_SHEETS_SA_JSON   service-account key: inline JSON or @/path/to.json
    RSA_SHEETS_ID        spreadsheet ID (or full URL)
    RSA_SHEETS_WORKSHEET worksheet name (default: GUI_QUEUE)
    RSA_SEC_USER_AGENT   SEC User-Agent "Name email" (recommended)

Examples:
    python -m src.edgar --window 14            # dry run, prints rows
    python -m src.edgar --window 14 --write    # append to GUI_QUEUE

"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from src.edgar.producer import (
    GUI_QUEUE_HEADER,
    append_gui_queue,
    discover,
    to_gui_rows,
)


def _load_sa_json(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("@"):
        return Path(raw[1:]).expanduser().read_text(encoding="utf-8")
    return raw


def main(argv: list[str] | None = None) -> int:
    """Run discovery; print rows (dry) or append them to GUI_QUEUE."""
    ap = argparse.ArgumentParser(prog="python -m src.edgar")
    ap.add_argument("--window", type=int, default=14, help="EFTS look-back days")
    ap.add_argument(
        "--write",
        action="store_true",
        help="Append to GUI_QUEUE (default: dry run, just print).",
    )
    ap.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip filing-body fetch (titles only; faster, less accurate).",
    )
    args = ap.parse_args(argv)

    fetch_errors: list[str] = []
    plays = discover(
        window_days=args.window,
        enrich=not args.no_enrich,
        errors=fetch_errors,
    )
    rows = to_gui_rows(plays)

    print("\t".join(GUI_QUEUE_HEADER))
    for r in rows:
        print("\t".join(str(c) for c in r))
    print(f"\n{len(rows)} alert-worthy play(s).", file=sys.stderr)

    if fetch_errors:
        print(
            f"WARNING: {len(fetch_errors)} EDGAR query/queries failed — "
            "results may be incomplete:",
            file=sys.stderr,
        )
        for e in fetch_errors:
            print(f"  - {e}", file=sys.stderr)
        # A run that fetched nothing AND hit fetch errors is a silent
        # missed-capture, not a genuinely empty window: exit non-zero so
        # an unattended cron/launchd job surfaces it instead of looking
        # clean.
        if not plays:
            print(
                "ERROR: every result was empty and EDGAR fetches failed — "
                "treating as a failed run (exit 3).",
                file=sys.stderr,
            )
            return 3

    if not args.write:
        print("(dry run — pass --write to append to GUI_QUEUE)", file=sys.stderr)
        return 0
    if not rows:
        return 0

    sa = _load_sa_json(os.getenv("RSA_SHEETS_SA_JSON", ""))
    sheet_id = os.getenv("RSA_SHEETS_ID", "").strip()
    worksheet = os.getenv("RSA_SHEETS_WORKSHEET", "GUI_QUEUE").strip()
    if not sa or not sheet_id:
        print(
            "ERROR: set RSA_SHEETS_SA_JSON and RSA_SHEETS_ID to --write.",
            file=sys.stderr,
        )
        return 2
    written = append_gui_queue(sa, sheet_id, rows, worksheet or "GUI_QUEUE")
    print(f"Appended {written} new row(s) to GUI_QUEUE.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
