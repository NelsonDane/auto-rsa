"""License manager: the single entry point for tier/cap decisions.

Every gate in the app (vault writes, GUI broker tiles, engine
preflight) calls into the four functions here so a future change
to the rule has exactly one home.

Decision flow:

1. Load the cached token from disk (``token_store.load()``).
2. Verify the Ed25519 signature with the embedded public key.
3. Check the payload's ``hardware_id`` matches this machine.
4. Check expiry against now (allow ``_GRACE_DAYS`` past expires_at —
   see ``docs/LICENSE_TIERS_DESIGN.md`` §11).
5. If any check fails → tier ``"unlicensed"`` (cap = 1).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from src.license import _keys, fingerprint, token_store, verify
from src.license.tiers import TIER_CAPS, TIER_LABEL, Tier

# Tokens past their expires_at are still honored for this many days
# so a brief outage doesn't degrade the friend's tier. Documented
# in §11 of the design doc.
_GRACE_DAYS = 7


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    # ``datetime.fromisoformat`` accepts the "Z" suffix natively from
    # 3.11 onward; no string surgery needed.
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _evaluate() -> dict[str, Any]:  # noqa: PLR0911
    """Resolve the active token into a decision record (never raises)."""
    out: dict[str, Any] = {
        "tier": "unlicensed",
        "cap": TIER_CAPS["unlicensed"],
        "expires_at": None,
        "license_id": None,
        "in_grace": False,
        "reason": "no token configured",
        "token_error": None,
    }
    token, load_error = token_store.load_with_status()
    if load_error is not None:
        # File present but unreadable/corrupt — distinct from "no
        # token." The GUI banner uses this to draw a red flag rather
        # than silently presenting the user as unlicensed (the same
        # state as fresh-install).
        out["reason"] = load_error
        out["token_error"] = load_error
        return out
    if token is None:
        return out
    if not verify.verify_token(token, _keys.PUBLIC_KEY_B64):
        out["reason"] = "token signature invalid"
        return out
    payload = token.get("payload", {})
    tier_value = str(payload.get("tier", ""))
    if tier_value not in TIER_CAPS:
        out["reason"] = f"unknown tier: {tier_value!r}"
        return out
    tier: Tier = tier_value  # type: ignore[assignment]
    bound_hw = str(payload.get("hardware_id", ""))
    if bound_hw != fingerprint.hardware_id():
        out["reason"] = "token bound to a different machine"
        return out
    expires = _parse_iso(payload.get("expires_at"))
    if expires is None:
        out["reason"] = "missing expires_at"
        return out
    now = _now()
    grace_until = expires + timedelta(days=_GRACE_DAYS)
    if now > grace_until:
        out["reason"] = "token expired beyond grace window"
        return out
    out.update(
        {
            "tier": tier,
            "cap": TIER_CAPS[tier],
            "expires_at": payload.get("expires_at"),
            "license_id": payload.get("license_id"),
            "in_grace": now > expires,
            "reason": "valid token" if now <= expires else "in grace window",
        },
    )
    return out


def current_tier() -> Tier:
    """Return the tier currently in effect (never raises)."""
    return _evaluate()["tier"]


def account_cap() -> int | None:
    """Return the parent broker cap for the active tier (None = unlimited)."""
    return _evaluate()["cap"]


def can_add_broker(current_count: int) -> tuple[bool, str | None]:
    """Whether one more parent broker can be added.

    Returns ``(True, None)`` to allow, or ``(False, reason)`` to
    block — the reason string is safe to surface in the GUI.
    """
    cap = account_cap()
    if cap is None or current_count < cap:
        return True, None
    tier_name = TIER_LABEL[current_tier()]
    return (
        False,
        f"{tier_name} tier permits {cap} parent broker login(s); "
        "delete an existing one first, or upgrade your license.",
    )


def status_summary() -> dict[str, Any]:
    """Everything the GUI banner needs in one call."""
    info = _evaluate()
    tier: Tier = info["tier"]
    cap = info["cap"]
    cap_text = "∞" if cap is None else str(cap)
    return {
        "tier": tier,
        "tier_label": TIER_LABEL[tier],
        "cap": cap,
        "cap_text": cap_text,
        "expires_at": info["expires_at"],
        "license_id": info["license_id"],
        "in_grace": info["in_grace"],
        "reason": info["reason"],
        # Non-None ONLY when the token file exists but couldn't be
        # parsed — distinct from "no token configured". GUI banner
        # promotes this to a red flag instead of silently showing
        # unlicensed (which a fresh install also shows).
        "token_error": info.get("token_error"),
        "hardware_id": fingerprint.hardware_id(),
    }
