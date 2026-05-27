"""On-disk cache for the signed license token.

Stored at ``creds/license.token`` (chmod 600 on POSIX). One JSON
object: ``{"payload": {...}, "signature": "<b64url>"}``. The
content is **not** secret (the signature prevents tampering, the
hardware binding stops cross-machine reuse), but we still lock the
permissions for hygiene.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

_TOKEN_PATH = Path(__file__).resolve().parents[2] / "creds" / "license.token"


def path() -> Path:
    """Return the on-disk token path (visible to tests + GUI status)."""
    return _TOKEN_PATH


def load() -> dict[str, Any] | None:
    """Read the cached token, or None if absent/unparseable."""
    p = path()
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def save(token: dict[str, Any]) -> None:
    """Persist a token atomically; chmod 600 on POSIX."""
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(token, indent=2), encoding="utf-8")
    with contextlib.suppress(OSError):
        tmp.chmod(0o600)
    tmp.replace(p)


def clear() -> None:
    """Remove the cached token (e.g. on 'Activate with a new key')."""
    with contextlib.suppress(FileNotFoundError):
        path().unlink()
