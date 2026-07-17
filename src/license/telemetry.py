"""Privacy-safe operator telemetry beacon (friend build).

Sends a SMALL, disclosed diagnostic beacon to the operator's license Worker so
the operator can see app versions, last-seen, and coarse error categories —
enough to catch a broken build or misuse, and nothing more.

What it sends: the signed license token (which the Worker issued), the app
version + OS tag, an event name, an optional coarse category from a FIXED
vocabulary, and a few integer counts.

What it NEVER sends: credentials, account numbers, holdings, tickers, dollar
amounts, order details, broker identities, or the vault — none of that leaves
the friend's machine.

Fail-safe: every send runs on a daemon thread with a short timeout and swallows
all errors, so telemetry can never block or break a run. Enabled by default in
a friend build; ``RSA_TELEMETRY=0`` disables it, ``=1`` forces it on elsewhere.
Disclosed in the app's License section.
"""

from __future__ import annotations

import contextlib
import os
import platform
import threading

import requests

from src.license import _keys, client, token_store

_TIMEOUT = 5
_TRUEY = frozenset({"1", "true", "yes", "on"})

# Coarse, non-identifying categories. Anything not here is dropped, so a call
# site can never accidentally leak free-form text (an account, a ticker) here.
_ALLOWED_CATEGORIES = frozenset({
    "", "startup", "broker_errors", "session_error", "engine_import_failed",
    "kill_ack", "no_license", "cap_block",
})
_COUNT_FIELDS = ("brokers", "errors", "cap_blocks")


def enabled() -> bool:
    """Return True when beacons should be sent.

    Friend build: on unless ``RSA_TELEMETRY=0``. Other builds: off unless
    ``RSA_TELEMETRY=1``. Always requires a configured license server.
    """
    raw = os.getenv("RSA_TELEMETRY")
    on = (
        raw.strip().lower() in _TRUEY
        if raw is not None
        else bool(getattr(_keys, "REQUIRE_LICENSE_TO_TRADE", False))
    )
    return on and bool(client.server_url())


def _app_version() -> str:
    with contextlib.suppress(Exception):
        from importlib.metadata import version  # noqa: PLC0415

        return version("auto_rsa_bot")
    return "0.0.0"


def _platform_tag() -> str:
    return f"{platform.system().lower()}-{platform.machine().lower()}"


def _clean_counts(counts: object) -> dict[str, int]:
    out: dict[str, int] = {}
    if isinstance(counts, dict):
        for k in _COUNT_FIELDS:
            v = counts.get(k)
            if isinstance(v, int) and not isinstance(v, bool):
                out[k] = max(0, min(99999, v))
    return out


def _send(event: str, outcome: str, category: str, counts: dict[str, int] | None) -> None:
    with contextlib.suppress(Exception):
        token = token_store.load()
        url = client.server_url()
        if not token or not url:
            return
        requests.post(
            f"{url}/telemetry",
            json={
                "token": token,
                "event": str(event)[:32],
                "outcome": str(outcome)[:16],
                "category": category if category in _ALLOWED_CATEGORIES else "",
                "app_version": _app_version(),
                "platform": _platform_tag(),
                "counts": _clean_counts(counts),
            },
            timeout=_TIMEOUT,
        )


def report(event: str, *, outcome: str = "", category: str = "", counts: dict[str, int] | None = None) -> None:
    """Fire a beacon (best-effort, off-thread). No-op if telemetry is off."""
    if not enabled():
        return
    with contextlib.suppress(Exception):
        threading.Thread(
            target=_send, args=(event, outcome, category, counts), daemon=True,
        ).start()
