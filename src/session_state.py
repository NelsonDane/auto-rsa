"""Broker session-health audit (read-only).

Step 1 of the persistent-sessions plan: inspect the on-disk session
artifacts each broker leaves in gitignored ``creds/`` and derive a
green / yellow / red health light per artifact, so a degrading session
demands attention *before* it silently stops capturing plays.

Read-only and network-free: it never logs in, never trades. It only
stats files and reads the local ledger. A real network "liveness
probe" is a later phase (needs an attended per-broker observation).

Health model:
* GREEN     fresh session artifact (age < 70% of TTL), or a stateless
            token broker that needs no session file.
* YELLOW    artifact approaching TTL (needs a refresh soon).

Health is LIVENESS-only. Trading activity is intentionally NOT a
health input: the reverse-split tickers are frequently unavailable or
restricted on a given broker, so "no recent buys" is expected and must
not degrade a healthy session. Activity + outcome reason codes
(src/outcomes.py) are shown as separate, non-alarming columns.
* RED       no artifact / artifact past TTL -> re-auth (login+2FA)
            needed. The auto-executor skips this broker and alerts.
* UNSUPPORTED  broker keeps no session (Selenium WF/Tornado, etc.) —
            interactive 2FA every run; informational, not an alarm.
* UNKNOWN   artifact path not yet confirmed for this broker.

TTL is configurable: ``RSA_SESSION_TTL_DAYS`` (default 6) plus an
optional ``RSA_SESSION_TTL_OVERRIDES`` JSON map ``{"broker": days}``.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterator

_CREDS = Path(__file__).resolve().parent.parent / "creds"
_DB_PATH = _CREDS / "sessions.db"
_LOCK = threading.Lock()

_DEFAULT_TTL_DAYS = 6
_GREEN_FRACTION = 0.70  # < this fraction of TTL old => green

GREEN = "GREEN"
YELLOW = "YELLOW"
RED = "RED"
UNSUPPORTED = "UNSUPPORTED"
UNKNOWN = "UNKNOWN"

# auth kinds
_TOKEN_FILE = "token_file"  # noqa: S105  # library token/pickle cache (Tier 1)
_STORAGE_STATE = "storage_state"  # Playwright storage_state (Fidelity)
_PROFILE_DIR = "profile_dir"  # browser profile directory
_STATELESS = "stateless"  # pure token/api-key, no session file
_EPHEMERAL = "ephemeral"  # no persistence at all (2FA every run)


class _Broker(NamedTuple):
    key: str
    kind: str
    glob: str | None  # None => path not yet confirmed
    note: str


# Only globs verified against the broker modules are asserted; brokers
# whose artifact path isn't confirmed are reported UNKNOWN, never guessed.
_BROKERS: tuple[_Broker, ...] = (
    _Broker("schwab", _TOKEN_FILE, "schwab*.json", "schwab-api session_cache"),
    _Broker("robinhood", _TOKEN_FILE, "robinhood*.pickle", "robin_stocks pickle"),
    _Broker("bbae", _TOKEN_FILE, "BBAE_*.pkl", "bbae-invest-api pickle"),
    _Broker("dspac", _TOKEN_FILE, "DSPAC_*.pkl", "dspac-invest-api pickle"),
    _Broker("fidelity", _STORAGE_STATE, "Fidelity*.json", "patchright storage_state"),
    _Broker("fennel", _STATELESS, None, "PAT token — no session file"),
    _Broker("public", _STATELESS, None, "API key — no session file"),
    _Broker("tradier", _STATELESS, None, "bearer token — no session file"),
    _Broker("chase", _PROFILE_DIR, "chase*", "nodriver browser profile dir"),
    _Broker("vanguard", _PROFILE_DIR, None, "profile path not yet confirmed"),
    _Broker("firstrade", _PROFILE_DIR, None, "profile path not yet confirmed"),
    _Broker("sofi", _PROFILE_DIR, None, "cookie pkl name not yet confirmed"),
    _Broker("wellsfargo", _PROFILE_DIR, "wellsfargo_profile", "Selenium persistent profile"),
    _Broker("tornado", _EPHEMERAL, None, "Selenium — no session persistence"),
    _Broker("webull", _EPHEMERAL, None, "no credential cache"),
    _Broker("tastytrade", _EPHEMERAL, None, "in-memory Session only"),
)


class SessionRecord(NamedTuple):
    """Health of one broker (optionally one artifact)."""

    broker: str
    artifact: str  # filename, or "-" / "(stateless)" / "(none)"
    health: str
    reason: str
    age_days: float | None
    last_order_at: str | None


def ttl_days(broker: str) -> int:
    """Return the configured TTL for a broker (default + override map)."""
    try:
        default = int(os.getenv("RSA_SESSION_TTL_DAYS", str(_DEFAULT_TTL_DAYS)))
    except ValueError:
        default = _DEFAULT_TTL_DAYS
    raw = os.getenv("RSA_SESSION_TTL_OVERRIDES", "").strip()
    if raw:
        try:
            ov = json.loads(raw)
            if isinstance(ov, dict) and broker in ov:
                return int(ov[broker])
        except (ValueError, TypeError):
            pass
    return default


def _last_order_at(broker: str) -> str | None:
    """Newest EXECUTED ledger timestamp for a broker, or None. Best-effort."""
    try:
        from src import ledger  # noqa: PLC0415

        rows = [
            r
            for r in ledger.list_executions()
            if str(r.get("broker", "")).lower() == broker
            and str(r.get("status")) == ledger.STATUS_EXECUTED
        ]
    except Exception:
        return None
    if not rows:
        return None
    return max(str(r.get("updated_at", "")) for r in rows) or None


def _age_days(path: Path) -> float:
    return max(0.0, (time.time() - path.stat().st_mtime) / 86400.0)


def _health_for(broker: _Broker) -> list[SessionRecord]:
    last = _last_order_at(broker.key)

    if broker.kind == _STATELESS:
        return [
            SessionRecord(
                broker.key, "(stateless)", GREEN,
                f"{broker.note}; always unattended-ready", None, last,
            ),
        ]
    if broker.kind == _EPHEMERAL:
        return [
            SessionRecord(
                broker.key, "(none)", UNSUPPORTED,
                f"{broker.note} — interactive 2FA each run", None, last,
            ),
        ]
    if broker.glob is None:
        return [
            SessionRecord(
                broker.key, "(unknown)", UNKNOWN,
                broker.note, None, last,
            ),
        ]

    matches = sorted(_CREDS.glob(broker.glob)) if _CREDS.exists() else []
    if not matches:
        return [
            SessionRecord(
                broker.key, "(none)", RED,
                "no saved session — login + 2FA required", None, last,
            ),
        ]

    ttl = ttl_days(broker.key)
    out: list[SessionRecord] = []
    for m in matches:
        # Health is LIVENESS-only — purely the session artifact's age vs
        # TTL. Trading activity is deliberately NOT a health input: these
        # low-float reverse-split tickers are routinely unavailable or
        # restricted on a given broker, so "no recent buys" is normal and
        # must never flip a healthy session yellow. last_order_at is
        # surfaced as an informational column instead, paired with the
        # outcome reason codes (src/outcomes.py) so the dashboard can show
        # *why* nothing was bought without alarming.
        age = _age_days(m)
        if age >= ttl:
            health, reason = RED, f"{age:.1f}d old > {ttl}d TTL — re-auth needed"
        elif age >= ttl * _GREEN_FRACTION:
            health, reason = YELLOW, f"approaching TTL ({age:.1f}/{ttl}d)"
        else:
            health, reason = GREEN, f"fresh ({age:.1f}/{ttl}d)"
        out.append(
            SessionRecord(broker.key, m.name, health, reason, round(age, 2), last),
        )
    return out


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=30, check_same_thread=False)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_health (
                broker TEXT NOT NULL,
                artifact TEXT NOT NULL,
                health TEXT NOT NULL,
                reason TEXT NOT NULL,
                age_days REAL,
                last_order_at TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (broker, artifact)
            )
            """,
        )
        yield conn
        conn.commit()
    finally:
        conn.close()


def audit(*, persist: bool = True) -> list[SessionRecord]:
    """Scan every broker's session artifact and return health records.

    Read-only w.r.t. brokers. When ``persist`` (default), the result is
    written to ``creds/sessions.db`` so the GUI Sessions panel and the
    auto-executor read a consistent snapshot.
    """
    records: list[SessionRecord] = []
    for b in _BROKERS:
        records.extend(_health_for(b))
    if persist:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with _LOCK, _connect() as conn:
            for r in records:
                conn.execute(
                    "INSERT INTO session_health (broker, artifact, health, "
                    "reason, age_days, last_order_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?) "
                    "ON CONFLICT(broker, artifact) DO UPDATE SET "
                    "health=excluded.health, reason=excluded.reason, "
                    "age_days=excluded.age_days, "
                    "last_order_at=excluded.last_order_at, "
                    "updated_at=excluded.updated_at",
                    (
                        r.broker, r.artifact, r.health, r.reason,
                        r.age_days, r.last_order_at, now,
                    ),
                )
    return records


def load_last_audit() -> list[dict[str, object]]:
    """Return the last persisted audit snapshot (for the GUI), newest first."""
    if not _DB_PATH.exists():
        return []
    with _LOCK, _connect() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT * FROM session_health ORDER BY broker, artifact",
        )
        return [dict(r) for r in cur.fetchall()]
