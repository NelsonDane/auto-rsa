"""CLI entry for the scheduled backup job: ``python -m src.backup``.

Reads the SA JSON from ``RSA_SHEETS_SA_JSON`` (same env var the
EDGAR producer uses — no duplicate config). The Drive folder ID
and backup passphrase come from ``creds/backup_config.json`` set
via the GUI sidebar.

Exit codes:
    0 — backup uploaded successfully.
    1 — config / runtime error (message printed to stderr).
    2 — operator hasn't configured backups yet.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from src.backup import config, run_backup
from src.backup.bundle import BackupError
from src.backup.drive import DriveError


def _load_sa_json(value: str) -> str:
    """Accept either inline JSON or a path to a JSON file."""
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith("{"):
        return value
    p = Path(value).expanduser()
    if p.is_file():
        return p.read_text(encoding="utf-8")
    return value


def main() -> int:
    """Run one backup; return process exit code."""
    if not config.is_configured():
        print(
            "Backup is not configured. Open the GUI sidebar's "
            "Backups section and save a folder ID + passphrase.",
            file=sys.stderr,
        )
        return 2
    sa = _load_sa_json(os.getenv("RSA_SHEETS_SA_JSON", ""))
    if not sa:
        print(
            "RSA_SHEETS_SA_JSON is not set (the scheduled job needs "
            "the SA JSON / path the EDGAR producer also uses).",
            file=sys.stderr,
        )
        return 1
    try:
        summary = run_backup(sa_json=sa)
    except (BackupError, DriveError) as exc:
        print(f"Backup failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"Uploaded {summary['uploaded']} "
        f"({summary['size_bytes']} bytes; "
        f"drive_file_id={summary['drive_file_id']}).",
    )
    if summary["retention_deleted"]:
        print(
            f"Retention swept {len(summary['retention_deleted'])} "
            f"older backup(s).",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
