"""Ed25519 signature verification with canonical JSON payload.

The token format is **detached**: a payload (JSON dict) is signed
separately from how it's stored. The on-disk form is one JSON
object with two top-level keys::

    {"payload": {...}, "signature": "<base64-url>"}

``payload`` is canonicalized (sorted keys, ``separators=(",", ":")``,
``ensure_ascii=False``) before signing **and** before verifying, so
a re-serialization that reorders keys or adds whitespace can't
break verification.

Spec'd in ``docs/LICENSE_TIERS_DESIGN.md`` §6.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PublicKey,
)


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    """Deterministic JSON bytes used for both sign + verify."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _decode_b64url(text: str) -> bytes:
    s = (text or "").strip()
    # base64url is URL-safe but may omit padding; restore it.
    pad = (-len(s)) % 4
    return base64.urlsafe_b64decode(s + ("=" * pad))


def verify_token(token: dict[str, Any], public_key_b64: str) -> bool:  # noqa: PLR0911
    """Return True iff the token's signature matches its payload.

    Pure: no I/O, no time check, no tier logic. Callers add the
    business rules (expiry, hardware binding) on top of a verified
    payload.

    Returns False — never raises — for any malformed input,
    unconfigured public key, or signature mismatch.
    """
    if not public_key_b64:
        return False
    try:
        pub = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(public_key_b64),
        )
    except (ValueError, TypeError):
        return False
    payload = token.get("payload")
    sig_b64 = token.get("signature")
    if not isinstance(payload, dict) or not isinstance(sig_b64, str):
        return False
    try:
        signature = _decode_b64url(sig_b64)
    except (ValueError, TypeError):
        return False
    try:
        pub.verify(signature, canonical_bytes(payload))
    except InvalidSignature:
        return False
    except Exception:
        return False
    return True
