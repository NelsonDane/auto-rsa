"""Encrypted off-site backup of vault + ledger + license.

This package bundles the operator's critical local state into a
single Fernet-encrypted tarball protected by a **separate** backup
passphrase (not the vault master) and uploads it to a configured
Google Drive folder using the existing service account.

Why separate passphrase: split fate. If the vault master is lost,
the live vault is gone — backups should still be recoverable. If
the operator forgets the backup passphrase, the live vault still
opens. One password leak doesn't compromise the other.

What's bundled (operator-confirmed):
- ``creds/vault.json``    — broker credentials
- ``creds/ledger.db``     — execution history (load-bearing for
                            dedupe; restoring a stale ledger could
                            cause double-buys)
- ``creds/license.token`` — cached license token (optional; the
                            operator can re-activate, but a fast
                            restore is convenient)

What's deliberately NOT bundled:
- ``creds/fp_salt``       — including it would let a restored backup
                            on a NEW machine compute the OLD
                            hardware_id, defeating per-machine
                            license binding. Excluded by design.
"""

from src.backup import config
from src.backup.bundle import (
    BackupError,
    create_bundle,
    restore_bundle,
)
from src.backup.drive import (
    DriveError,
    delete_from_drive,
    download_from_drive,
    list_backups,
    upload_to_drive,
)
from src.backup.runner import (
    backup_filename,
    run_backup,
    run_restore,
)

__all__ = [
    "BackupError",
    "DriveError",
    "backup_filename",
    "config",
    "create_bundle",
    "delete_from_drive",
    "download_from_drive",
    "list_backups",
    "restore_bundle",
    "run_backup",
    "run_restore",
    "upload_to_drive",
]
