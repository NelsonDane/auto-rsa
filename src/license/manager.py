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

import contextlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.license import _keys, fingerprint, token_store, verify
from src.license.tiers import SUBACCOUNT_CAPS, TIER_CAPS, TIER_LABEL, Tier

# Tokens past their expires_at are still honored for this many days
# so a brief outage doesn't degrade the friend's tier. Documented
# in §11 of the design doc.
_GRACE_DAYS = 7

# Development / self-hosted-operator bypass. Disables the broker-
# count cap entirely. Two ways to enable, in priority order:
#
# 1. ``RSA_LICENSE_BYPASS=1`` env var (headless / scripted use).
# 2. Sentinel file at ``creds/license_bypass.flag`` (GUI toggle —
#    the License sidebar section creates/deletes this file). Lives
#    alongside vault.json which is already gitignored. Operator-
#    friendly: no env editing required on Windows boxes that don't
#    have a .env file.
#
# The tier banner shows "Operator (bypass)" in yellow when active
# so the operator can SEE the gate is off and isn't accidentally
# shipping it that way.
_BYPASS_ENV = "RSA_LICENSE_BYPASS"
_BYPASS_FLAG_PATH = (
    Path(__file__).resolve().parents[2] / "creds" / "license_bypass.flag"
)


def _bypass_env_active() -> bool:
    return os.getenv(_BYPASS_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _bypass_flag_active() -> bool:
    """Return True iff the sentinel file exists.

    Best-effort: any I/O weirdness (perm denied, racing delete)
    reports False so we never SILENTLY bypass when the operator
    didn't intend to.
    """
    try:
        return _BYPASS_FLAG_PATH.is_file()
    except OSError:
        return False


def _bypass_active() -> bool:
    # SECURITY: the operator's dev bypass (env var / sentinel file) must be
    # UNREACHABLE in a friend build. Otherwise a friend could set
    # RSA_LICENSE_BYPASS=1 or drop creds/license_bypass.flag and lift their
    # own caps to operator/unlimited. A friend build bakes
    # REQUIRE_LICENSE_TO_TRADE=True (compiled in), so honor the bypass only
    # when it's False (the self-hosted operator / pro build).
    if getattr(_keys, "REQUIRE_LICENSE_TO_TRADE", False):
        return False
    return _bypass_env_active() or _bypass_flag_active()


def bypass_flag_path() -> Path:
    """Path to the sentinel file (for GUI to create/delete)."""
    return _BYPASS_FLAG_PATH


def set_bypass_flag(*, enabled: bool) -> None:
    """Create or remove the sentinel file. Idempotent.

    Used by the GUI's License sidebar toggle. Touches no other
    state. The env-var bypass (if set) overrides this flag —
    they OR together.
    """
    if enabled:
        _BYPASS_FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _BYPASS_FLAG_PATH.write_text(
            "Presence of this file disables the license broker-count cap.\n"
            "Created/removed by the GUI's License sidebar toggle.\n"
            "Delete to re-enable the license gate.\n",
            encoding="utf-8",
        )
        with contextlib.suppress(OSError):
            _BYPASS_FLAG_PATH.chmod(0o600)
    else:
        with contextlib.suppress(FileNotFoundError):
            _BYPASS_FLAG_PATH.unlink()


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
    if _bypass_active():
        # Operator-level cap (unlimited); reason makes the bypass
        # visible in the GUI banner so it can't be left on by
        # accident. Token-error / expiry are short-circuited.
        return {
            "tier": "operator",
            "cap": None,
            "expires_at": None,
            "license_id": "BYPASS",
            "in_grace": False,
            "reason": f"{_BYPASS_ENV}=1 — license gating disabled",
            "token_error": None,
        }
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
        # Distinguish a genuine machine change from "couldn't read this
        # machine's hardware id" (which yields a fallback fingerprint
        # that won't match the bound one). The latter is an actionable
        # transient, not a real re-bind — surface it so a legit user on
        # the same box isn't silently and confusingly downgraded.
        if fingerprint.using_fallback_id():
            out["reason"] = (
                "could not read this machine's hardware id "
                "(using fallback) — license temporarily unverified"
            )
            out["token_error"] = "hardware_id_unreadable"
        else:
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


def subaccount_cap() -> int | None:
    """Accounts-per-broker cap for the active tier (None = unlimited).

    The Friend tiers cap this at 1 (no multi-account fan-out). Reads
    ``current_tier()`` so the operator bypass (→ operator) and every
    grace/expiry rule apply automatically.

    In a FRIEND build (``REQUIRE_LICENSE_TO_TRADE``), an ``unlicensed``
    fallback is tightened to 1: a lapsed friend token drops to
    ``unlicensed`` and the trading gate fails open when offline, so
    leaving it uncapped would let a friend with no valid license trade
    every account. The pro build leaves ``unlicensed`` uncapped (its
    "try one broker" state is unchanged); bypass (→ operator) is always
    uncapped.
    """
    tier = current_tier()
    cap = SUBACCOUNT_CAPS.get(tier)
    if (
        cap is None
        and tier == "unlicensed"
        and getattr(_keys, "REQUIRE_LICENSE_TO_TRADE", False)
    ):
        return 1
    return cap


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
