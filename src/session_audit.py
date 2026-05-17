"""Read-only broker session-health audit CLI.

    python -m src.session_audit

Never logs in, never trades — only inspects creds/ artifacts and the
local ledger, prints a green/yellow/red table, and persists the
snapshot for the GUI Sessions panel. Safe to run on a schedule.
"""

from __future__ import annotations

import sys

from src.session_state import GREEN, RED, UNSUPPORTED, YELLOW, audit

_DOT = {GREEN: "🟢", YELLOW: "🟡", RED: "🔴", UNSUPPORTED: "⚪"}


def main(argv: list[str] | None = None) -> int:
    """Print the session-health table; exit 1 if any broker is RED."""
    records = audit(persist="--no-persist" not in (argv or sys.argv[1:]))
    width = max((len(r.broker) for r in records), default=6)
    print(f"{'BROKER':<{width}}  ST  {'ARTIFACT':<22} REASON")
    any_red = False
    for r in sorted(records, key=lambda x: (x.health != RED, x.broker)):
        any_red = any_red or r.health == RED
        dot = _DOT.get(r.health, "❔")
        print(f"{r.broker:<{width}}  {dot}  {r.artifact:<22} {r.reason}")
    reds = sum(r.health == RED for r in records)
    print(f"\n{len(records)} artifact(s); {reds} need re-auth (RED).",
          file=sys.stderr)
    return 1 if any_red else 0


if __name__ == "__main__":
    raise SystemExit(main())
