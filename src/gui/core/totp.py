"""Validate/normalize TOTP authenticator secrets before they're stored.

A TOTP secret is base32 (letters A-Z and digits 2-7). Catching a bad
one at save time avoids a wasted broker login - for Fidelity that also
avoids tripping anti-bot escalation. Validation mirrors exactly what
`pyotp` does at runtime (``base64.b32decode(secret, casefold=True)``),
so "passes here" guarantees "pyotp will accept it".

Common bad inputs this catches: a Symantec VIP *Credential ID*
(VSMT... - contains 0/1/8/9), a 6-digit code, an ``otpauth://`` URI, or a
key pasted with spaces/dashes.
"""

from __future__ import annotations

import base64
import binascii

_NA_SENTINELS = {"", "NA"}


def normalize_totp_secret(value: str) -> tuple[str | None, str | None]:
    """Return (normalized_secret, error).

    Blank or the ``NA`` sentinel (meaning "no TOTP / 2FA not enabled")
    passes through unchanged with no error. Otherwise the value is
    upper-cased with spaces/dashes removed and validated as base32;
    on failure ``(None, message)`` is returned.
    """
    raw = (value or "").strip()
    if raw.upper() in _NA_SENTINELS:
        return raw, None
    if raw.lower().startswith("otpauth://"):
        return None, (
            "Paste only the secret key, not the whole otpauth:// URI."
        )
    norm = raw.replace(" ", "").replace("-", "").upper()
    try:
        # Exactly what pyotp does at runtime - no extra padding.
        base64.b32decode(norm, casefold=True)
    except (binascii.Error, ValueError):
        return None, (
            "Not a valid authenticator (base32) key. Use the manual-entry "
            "key from the broker's authenticator-app setup - letters A-Z "
            "and digits 2-7 only. It is NOT a Symantec VIP Credential ID "
            "(VSMT...) or a 6-digit code."
        )
    return norm, None
