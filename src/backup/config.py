"""On-disk config for the backup feature.

Stored at ``creds/backup_config.json`` (chmod 600 on POSIX). Lives
alongside the encrypted vault but is intentionally NOT inside the
vault: the scheduled launchd backup job runs without the master
password, so the config it needs (Drive folder ID + backup
passphrase) has to be readable unattended.

The threat model: the backup passphrase protects the **backup
blob** in Drive. If an attacker has filesystem access to the Mac
Mini, they already have the unencrypted ledger and the SA JSON —
the backup passphrase being on the same disk does not weaken the
overall posture. The split-fate property still holds: a leaked
backup blob WITHOUT the passphrase reveals nothing, and a
forgotten vault master password doesn't lock you out of backups.

Service-account JSON is **not** stored here — it's pulled from the
vault at backup time (manual) or from the ``RSA_SHEETS_SA_JSON``
env var (scheduled). Same source of truth as the EDGAR producer.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "creds" / "backup_config.json"
)

# Default retention: keep this many of the most-recent backups; the
# rest are deleted from Drive on the next save. Configurable per-install.
DEFAULT_RETENTION = 12


def path() -> Path:
    """Return the on-disk config path."""
    return _CONFIG_PATH


def load() -> dict[str, Any]:
    """Return the saved config, or an empty dict if absent/unparseable."""
    p = path()
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def save(
    *,
    drive_folder_id: str,
    passphrase: str,
    retention: int = DEFAULT_RETENTION,
) -> None:
    """Persist backup config atomically; chmod 600 on POSIX.

    Both ``drive_folder_id`` and ``passphrase`` must be non-empty; the
    caller (GUI) is responsible for trimming whitespace.
    """
    if not drive_folder_id:
        msg = "Drive folder ID cannot be empty."
        raise ValueError(msg)
    if not passphrase:
        msg = "Backup passphrase cannot be empty."
        raise ValueError(msg)
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    cfg = {
        "drive_folder_id": drive_folder_id,
        "passphrase": passphrase,
        "retention": int(retention) if retention else DEFAULT_RETENTION,
    }
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    with contextlib.suppress(OSError):
        tmp.chmod(0o600)
    tmp.replace(p)


def is_configured() -> bool:
    """Return True iff both the folder ID and passphrase are set."""
    cfg = load()
    return bool(cfg.get("drive_folder_id")) and bool(cfg.get("passphrase"))


def clear() -> None:
    """Remove the backup config (e.g. operator unconfigured backups)."""
    with contextlib.suppress(FileNotFoundError):
        path().unlink()
