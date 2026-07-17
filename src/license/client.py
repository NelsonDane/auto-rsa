"""Client side of the license Worker: activate, refresh, kill-switch.

The only module that talks to the network. It stays thin — no tier
logic (that's ``manager.py``) — and it TRUSTS THE SIGNATURE, NOT THE
SERVER: every token returned by the Worker is re-verified with the
embedded public key before it is written to disk, so a rogue or
compromised server still cannot mint a token the app accepts without
the private key.

Fail-safe posture:
* ``activate`` reports a friendly message on every failure; never
  writes a token that doesn't verify.
* ``refresh_if_stale`` swallows all errors — a brief outage keeps the
  cached token working through the grace window (manager.py §11).
* ``killswitch_status`` FAILS OPEN on a network error (a Cloudflare
  blip must not freeze a friend); the operator pairs kill with revoke
  for a hard stop. See docs/CLOUDFLARE_LICENSE_BUILD.md §4.3.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import platform
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from src.license import _keys, fingerprint, token_store, verify

# Short so a slow/offline server never wedges startup.
_TIMEOUT = 8
# Refresh a token older than this (well inside the 30-day token life).
_REFRESH_AFTER_DAYS = 7
# Kill-switch answer is cached this long so the pre-trade check is cheap.
_KILL_CACHE_TTL = 60

_kill_cache: dict[str, Any] = {"ts": 0.0, "value": None}


def server_url() -> str:
    """Base URL of the license Worker (env override wins over the baked-in)."""
    return (os.getenv("RSA_LICENSE_SERVER_URL") or _keys.ACTIVATION_URL or "").rstrip("/")


def _app_version() -> str:
    with contextlib.suppress(Exception):
        from importlib.metadata import version  # noqa: PLC0415

        return version("auto_rsa_bot")
    return "0.0.0"


def _hostname_hash() -> str:
    # SHA-256 of the hostname, never the hostname itself.
    with contextlib.suppress(Exception):
        return hashlib.sha256(platform.node().encode("utf-8")).hexdigest()
    return ""


def _platform_tag() -> str:
    return f"{platform.system().lower()}-{platform.machine().lower()}"


def _strip(token: dict[str, Any]) -> dict[str, Any]:
    """Persist only the signed parts (drop server extras like account_cap)."""
    return {"payload": token.get("payload"), "signature": token.get("signature")}


def _hardware_matches(token: dict[str, Any]) -> bool:
    payload = token.get("payload") or {}
    return str(payload.get("hardware_id", "")) == fingerprint.hardware_id()


def _safe_msg(resp: requests.Response) -> str:
    with contextlib.suppress(Exception):
        return str(resp.json().get("message", ""))
    return ""


def _is_stale(token: dict[str, Any]) -> bool:
    payload = token.get("payload") or {}
    issued = payload.get("issued_at")
    if not isinstance(issued, str):
        return True  # unknown age -> refresh
    with contextlib.suppress(ValueError):
        dt = datetime.fromisoformat(issued)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return datetime.now(UTC) - dt > timedelta(days=_REFRESH_AFTER_DAYS)
    return True


def activate(license_key: str) -> tuple[bool, str]:
    """Bind this machine and store a signed token. Returns (ok, message)."""
    url = server_url()
    if not url:
        return False, "No license server is configured in this build."
    key = (license_key or "").strip()
    if not key:
        return False, "Enter your license key."
    try:
        resp = requests.post(
            f"{url}/activate",
            json={
                "license_key": key,
                "hardware_id": fingerprint.hardware_id(),
                "hostname_hash": _hostname_hash(),
                "app_version": _app_version(),
                "platform": _platform_tag(),
            },
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        return False, f"Could not reach the license server: {exc}"

    friendly = {
        404: "License key not recognized.",
        409: "This license is already active on another machine — "
        "ask the operator to move it.",
        410: "This license has been revoked or has expired.",
    }
    if resp.status_code in friendly:
        return False, friendly[resp.status_code]
    if resp.status_code == 423:
        return False, _safe_msg(resp) or "Activation is paused by the operator."
    if resp.status_code != 200:
        return False, f"Activation failed (HTTP {resp.status_code})."

    try:
        token = resp.json()
    except ValueError:
        return False, "Activation response was not valid."
    # Trust the SIGNATURE, not the server.
    if not verify.verify_token(token, _keys.PUBLIC_KEY_B64):
        return False, "Activation response failed its signature check."
    if not _hardware_matches(token):
        return False, "Activation was issued for a different machine."
    token_store.save(_strip(token))
    return True, "Activated."


def refresh_now() -> tuple[bool, str]:
    """Force a token refresh regardless of age. Returns (ok, message).

    Used by the GUI's "Refresh" button. Verifies the returned token's
    signature before saving (trust the signature, not the server).
    """
    url = server_url()
    if not url:
        return False, "No license server is configured in this build."
    token = token_store.load()
    if not token:
        return False, "No license token to refresh — activate a key first."
    try:
        resp = requests.post(
            f"{url}/refresh",
            json={"token": token, "app_version": _app_version()},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        return False, f"Could not reach the license server: {exc}"
    if resp.status_code == 410:
        return False, "This license has been revoked or has expired."
    if resp.status_code == 423:
        return False, _safe_msg(resp) or "Refresh is paused by the operator."
    if resp.status_code != 200:
        return False, f"Refresh failed (HTTP {resp.status_code})."
    try:
        new = resp.json()
    except ValueError:
        return False, "Refresh response was not valid."
    if verify.verify_token(new, _keys.PUBLIC_KEY_B64) and _hardware_matches(new):
        token_store.save(_strip(new))
        return True, "License refreshed."
    return False, "Refresh response failed its signature check."


def refresh_if_stale() -> None:
    """Silently refresh a stale token on app start. All errors swallowed."""
    token = token_store.load()
    if token and _is_stale(token):
        with contextlib.suppress(Exception):
            refresh_now()


def killswitch_status() -> dict[str, Any]:
    """Return the kill-switch state. Cached ~60s. FAILS OPEN on error.

    Keys: ``active`` (bool), ``message`` (str), ``min_app_version`` (str),
    ``reachable`` (bool — False when the server couldn't be reached, so a
    caller can distinguish "confirmed not killed" from "couldn't ask").
    """
    now = time.monotonic()
    cached = _kill_cache["value"]
    if cached is not None and now - float(_kill_cache["ts"]) < _KILL_CACHE_TTL:
        return cached  # type: ignore[return-value]

    result: dict[str, Any] = {
        "active": False,
        "message": "",
        "min_app_version": "",
        "reachable": False,
    }
    url = server_url()
    if url:
        try:
            resp = requests.get(
                f"{url}/killswitch",
                params={"app_version": _app_version()},
                timeout=_TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json()
                result = {
                    "active": bool(data.get("active")),
                    "message": str(data.get("message", "")),
                    "min_app_version": str(data.get("min_app_version", "")),
                    "reachable": True,
                }
        except (requests.RequestException, ValueError):
            pass  # FAIL-OPEN: active stays False, reachable stays False
            # (ValueError = a 200 with a body we couldn't parse.)

    _kill_cache["ts"] = now
    _kill_cache["value"] = result
    return result


def order_placement_blocked() -> tuple[bool, str]:
    """Kill-switch-only gate: (True, message) if the kill switch says stop.

    Used by the GUI License banner. The engine uses :func:`pre_trade_block`,
    which additionally catches revoke and (in a Friend build) an absent
    license. Fail-open on a network error.
    """
    ks = killswitch_status()
    if ks.get("active"):
        return True, str(ks.get("message") or "Trading is paused by the operator.")
    return False, ""


def pre_trade_block(*, require_license: bool) -> tuple[bool, str]:
    """Authoritative pre-trade gate. Returns (blocked, reason).

    A single live check that catches all three stop conditions:

    * **Killed**  — a live ``/refresh`` returns 423 (the switch is on).
    * **Revoked / expired** — ``/refresh`` returns 410; the stale token is
      cleared so the friend is unlicensed from here on.
    * **No license** — only when ``require_license`` (the Friend build):
      an install that never activated places no orders.

    FAILS OPEN on a network error or an unconfigured server (returns
    ``(False, "")``) so a Cloudflare blip never freezes a legitimate run;
    revoke is the hard backstop and bites the next time the friend is
    online. A valid ``/refresh`` also silently rotates the token.
    """
    url = server_url()
    if not url:
        return False, ""  # unconfigured -> can't enforce; fail open

    token = token_store.load()
    if token:
        try:
            resp = requests.post(
                f"{url}/refresh",
                json={"token": token, "app_version": _app_version()},
                timeout=_TIMEOUT,
            )
        except requests.RequestException:
            return False, ""  # offline -> fail open (grace)
        if resp.status_code == 200:
            # 200 = valid, not killed, not revoked -> allow. Rotate the
            # token when the body parses; a garbage 200 still allows (200
            # is not a block signal) rather than raising.
            try:
                new = resp.json()
            except ValueError:
                return False, ""
            if verify.verify_token(new, _keys.PUBLIC_KEY_B64) and _hardware_matches(new):
                token_store.save(_strip(new))
            return False, ""
        if resp.status_code == 410:
            token_store.clear()
            return True, (
                "Your license has been revoked or has expired — contact the "
                "operator. No orders were placed."
            )
        if resp.status_code == 423:
            return True, _safe_msg(resp) or "Trading is paused by the operator."
        return False, ""  # unexpected status -> fail open

    # No token on disk.
    if require_license:
        return True, (
            "No license is activated — activate your key in the License "
            "section to place orders."
        )
    # Pro build with no token: only the kill switch gates trading.
    return order_placement_blocked()
