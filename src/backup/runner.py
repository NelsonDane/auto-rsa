"""High-level orchestrator for one backup run.

Used by both the GUI's manual "Back up now" button and the
scheduled launchd job (``python -m src.backup``). Single function
``run_backup`` so both paths produce identical results.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

from src.backup import bundle as _bundle
from src.backup import config as _config
from src.backup import drive as _drive

_CREDS_DIR = Path(__file__).resolve().parents[2] / "creds"

# Files the backup includes if present. Operator-confirmed in the
# AskUserQuestion flow; fp_salt is deliberately excluded so a
# restore on a new machine doesn't defeat hardware binding.
_BACKUP_PATHS: tuple[str, ...] = (
    "vault.json",
    "ledger.db",
    "license.token",
)


def _stamp(now: _dt.datetime | None = None) -> str:
    n = now or _dt.datetime.now(_dt.UTC)
    return n.strftime("%Y-%m-%dT%H-%M-%SZ")


def backup_filename(prefix: str = "rsa-backup", now: _dt.datetime | None = None) -> str:
    """Return a sortable filename for a new backup."""
    return f"{prefix}-{_stamp(now)}.bin"


def run_backup(
    *,
    sa_json: str,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    """Create + upload one backup and run retention.

    The Drive folder ID and passphrase come from
    ``creds/backup_config.json`` (set via the GUI). ``sa_json`` is
    passed in by the caller — the GUI pulls it from the vault's
    Sheets config; the scheduled job reads it from the
    ``RSA_SHEETS_SA_JSON`` env var. Same SA in both cases.

    Returns a summary dict for surfacing in logs / the GUI:

        {"uploaded": "rsa-backup-...bin", "drive_file_id": "...",
         "size_bytes": N, "retention_deleted": [...]}
    """
    cfg = _config.load()
    folder_id = cfg.get("drive_folder_id", "").strip()
    passphrase = cfg.get("passphrase", "")
    retention = int(cfg.get("retention", _config.DEFAULT_RETENTION) or 1)
    if not folder_id or not passphrase:
        msg = (
            "Backup is not configured. Open the GUI sidebar's "
            "Backups section and save a folder ID + passphrase."
        )
        raise _bundle.BackupError(msg)

    paths = [_CREDS_DIR / name for name in _BACKUP_PATHS]
    blob = _bundle.create_bundle(passphrase, paths)
    name = backup_filename(now=now)
    meta = _drive.upload_to_drive(sa_json, folder_id, name, blob)

    # Retention sweep: keep the N newest (including the one we just
    # uploaded), delete the rest. list_backups returns newest-first.
    deleted: list[str] = []
    try:
        existing = _drive.list_backups(sa_json, folder_id, max_results=200)
    except _drive.DriveError:
        existing = []  # retention is best-effort
    for stale in existing[retention:]:
        try:
            _drive.delete_from_drive(sa_json, stale["id"])
            deleted.append(stale.get("name", stale["id"]))
        except _drive.DriveError:
            # One stale-delete failure shouldn't fail the whole backup.
            continue

    return {
        "uploaded": name,
        "drive_file_id": meta.get("id", ""),
        "size_bytes": len(blob),
        "retention_deleted": deleted,
    }


def run_restore(
    *,
    sa_json: str,
    file_id: str,
    passphrase: str,
    dest_dir: Path | None = None,
) -> list[str]:
    """Download + decrypt + extract a chosen backup.

    Restoring overwrites whichever of ``vault.json`` / ``ledger.db`` /
    ``license.token`` exist in the bundle. The GUI MUST instruct the
    operator to restart Streamlit afterwards — the in-memory vault
    state otherwise lags the restored on-disk state.
    """
    blob = _drive.download_from_drive(sa_json, file_id)
    target = dest_dir or _CREDS_DIR
    return _bundle.restore_bundle(passphrase, blob, target)
