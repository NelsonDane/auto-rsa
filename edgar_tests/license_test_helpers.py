"""Deterministic Ed25519 signing fixture for license tests.

The private key here is **a test-only key**, fine to commit — it
only signs synthetic tokens consumed by the local test suite. The
production public key (``src.license._keys.PUBLIC_KEY_B64``) is a
different key the operator manages off-machine.

Tests monkey-patch ``src.license._keys.PUBLIC_KEY_B64`` to the
public half here so synthetic tokens verify; production builds are
untouched.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from src.license import verify

# 32-byte raw seed for a stable test private key. Deterministic so
# golden-vector tests catch accidental signature/canonicalization
# changes across refactors.
_TEST_SEED = b"\x01" * 32


def _priv() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(_TEST_SEED)


def public_key_b64() -> str:
    """Base64 of the raw public key matching ``_TEST_SEED``."""
    pub = _priv().public_key().public_bytes_raw()
    return base64.b64encode(pub).decode()


def sign_token(payload: dict[str, Any]) -> dict[str, Any]:
    """Return ``{payload, signature}`` for the given payload."""
    sig = _priv().sign(verify.canonical_bytes(payload))
    return {
        "payload": payload,
        "signature": base64.urlsafe_b64encode(sig).rstrip(b"=").decode(),
    }


def fresh_payload(
    *,
    tier: str = "advanced",
    hardware_id: str,
    days_until_expiry: int = 30,
    license_id: str = "lic-test-0001",
) -> dict[str, Any]:
    """Build a realistic payload for activation-style tests."""
    now = datetime.now(UTC)
    return {
        "license_id": license_id,
        "tier": tier,
        "hardware_id": hardware_id,
        "issued_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(days=days_until_expiry))
        .isoformat()
        .replace("+00:00", "Z"),
    }


def write_token(tmp_path, payload: dict[str, Any]) -> None:
    """Persist a signed token to ``creds/license.token`` under ``tmp_path``."""
    token = sign_token(payload)
    creds = tmp_path / "creds"
    creds.mkdir(parents=True, exist_ok=True)
    (creds / "license.token").write_text(json.dumps(token), encoding="utf-8")
