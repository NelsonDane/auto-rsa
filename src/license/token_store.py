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
    """Read the cached token, or None if absent/unparseable.

    Prefer :func:`load_with_status` when the caller needs to
    distinguish "no token" from "token unreadable/corrupt" — the
    latter is a silent-downgrade footgun for the GUI banner.
    """
    token, _ = load_with_status()
    return token


def load_with_status() -> tuple[dict[str, Any] | None, str | None]:
    """Read the token AND return a human-safe error string if any.

    Returns ``(token, None)`` on success or absence (no file = no
    error; that's the no-license-yet state). Returns
    ``(None, "<reason>")`` when the file exists but cannot be read
    or parsed — so the GUI can surface a yellow/red banner instead
    of silently presenting the user as unlicensed.
    """
    p = path()
    if not p.exists():
        return None, None
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"token file unreadable: {exc}"
    try:
        data = json.loads(text)
    except ValueError as exc:
        return None, f"token file is not valid JSON: {exc}"
    if not isinstance(data, dict):
        return None, "token file does not contain a JSON object"
    return data, None


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
