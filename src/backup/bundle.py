r"""Encrypted tarball: vault + ledger + license token.

Format:

    salt(16 bytes raw) || kdf_json + b"\n" || fernet_token

* ``salt`` is a fresh per-backup random value.
* ``kdf_json`` is a JSON dict ``{"n":..., "r":..., "p":...}`` so a
  future params upgrade can still decrypt old backups.
* ``fernet_token`` is the encrypted tar.gz blob.

The same scrypt parameters as the vault (``2**16, r=8, p=1``) are
used; the backup passphrase is intentionally distinct from the
vault master so a single password compromise doesn't affect both.
"""

from __future__ import annotations

import base64
import io
import json
import secrets
import tarfile
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

if TYPE_CHECKING:
    from pathlib import Path

_SALT_BYTES = 16
_KEY_LEN = 32
# Same as the vault's strong KDF — see src/gui/core/vault.py._STRONG_KDF.
_KDF_PARAMS: dict[str, int] = {"n": 2**16, "r": 8, "p": 1}


class BackupError(Exception):
    """Raised for any bundle create / restore failure (message user-safe)."""


def _derive_key(passphrase: str, salt: bytes, kdf: dict[str, int]) -> bytes:
    scrypt = Scrypt(
        salt=salt, length=_KEY_LEN,
        n=kdf["n"], r=kdf["r"], p=kdf["p"],
    )
    return base64.urlsafe_b64encode(scrypt.derive(passphrase.encode("utf-8")))


def create_bundle(passphrase: str, paths: list[Path]) -> bytes:
    """Bundle the given files into an encrypted tarball.

    ``paths`` may include missing entries — they're silently skipped
    so a restored install without a license token still backs up
    cleanly. At least one path must exist or :class:`BackupError`
    is raised (avoids producing a useless empty bundle).
    """
    if not passphrase:
        msg = "Backup passphrase cannot be empty."
        raise BackupError(msg)
    existing: list[Path] = [p for p in paths if p.is_file()]
    if not existing:
        msg = "None of the requested files exist on disk; nothing to back up."
        raise BackupError(msg)

    # Build the tar in memory. arcname is just the filename, not the
    # full path, so restore drops files cleanly into a target dir.
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for p in existing:
            tar.add(str(p), arcname=p.name)
    tarball = buf.getvalue()

    salt = secrets.token_bytes(_SALT_BYTES)
    kdf = dict(_KDF_PARAMS)
    key = _derive_key(passphrase, salt, kdf)
    token = Fernet(key).encrypt(tarball)

    header = json.dumps(kdf, separators=(",", ":")).encode("utf-8")
    return salt + header + b"\n" + token


def restore_bundle(
    passphrase: str, blob: bytes, dest_dir: Path,
) -> list[str]:
    """Decrypt + extract a bundle into ``dest_dir``; return filenames.

    Refuses to traverse outside ``dest_dir`` (defends against a
    tampered tar that contains ``../``). Files are written with the
    default umask; the caller may chmod 600 after if desired.
    """
    if not passphrase:
        msg = "Backup passphrase cannot be empty."
        raise BackupError(msg)
    if len(blob) < _SALT_BYTES + 4:
        msg = "Bundle is too short to be valid."
        raise BackupError(msg)
    salt = blob[:_SALT_BYTES]
    rest = blob[_SALT_BYTES:]
    try:
        header, token = rest.split(b"\n", 1)
    except ValueError as exc:
        msg = "Bundle header is malformed (no newline separator)."
        raise BackupError(msg) from exc
    try:
        kdf = json.loads(header)
        kdf_int = {k: int(kdf[k]) for k in ("n", "r", "p")}
    except (ValueError, TypeError, KeyError) as exc:
        msg = f"Bundle KDF header is not valid JSON or is missing fields: {exc}"
        raise BackupError(msg) from exc
    key = _derive_key(passphrase, salt, kdf_int)
    try:
        tarball = Fernet(key).decrypt(token)
    except InvalidToken as exc:
        msg = "Wrong passphrase, or the bundle is corrupt."
        raise BackupError(msg) from exc

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_dir = dest_dir.resolve()
    written: list[str] = []
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            target = (dest_dir / member.name).resolve()
            # Path-traversal guard. Use real path containment, not a
            # string prefix: ``str.startswith`` lets a sibling dir that
            # merely shares the prefix (e.g. ``creds-evil/x`` vs
            # ``creds``) escape the destination. An absolute or ``..``
            # member name that resolves outside dest_dir is rejected here.
            if dest_dir != target and dest_dir not in target.parents:
                msg = (
                    f"Bundle contains a path-traversing entry "
                    f"({member.name!r}); refusing to restore."
                )
                raise BackupError(msg)
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            target.write_bytes(extracted.read())
            written.append(member.name)
    return written
