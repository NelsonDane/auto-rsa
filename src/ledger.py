"""Execution ledger — the safety spine for reverse-split automation.

Records every real (non-dry) order intent and outcome keyed by
``(key, broker, sub_account, ticker, action)`` so a play is never
executed twice. One whole share per account is all that's needed to
capture a reverse-split round-up; this ledger is what prevents a retry,
crash-resume, or re-queued signal from buying again.

Lives next to ``helper_api`` (not under ``gui/``) so the engine
subprocess and broker modules can import it without a GUI dependency.
The DB file sits in ``creds/`` which is fully gitignored.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterator

_DB_PATH = Path(__file__).resolve().parent.parent / "creds" / "ledger.db"
_LOCK = threading.Lock()

# Statuses. EXECUTED and INTENDED both block a re-attempt: EXECUTED is an
# obvious double-buy; INTENDED means an order was started but its outcome
# is unknown (crash mid-order), so auto-retrying it risks a double-buy —
# it must be resolved by a human, not silently retried. FAILED is safe to
# retry (no order reached the broker, or it was rejected).
STATUS_INTENDED = "INTENDED"
STATUS_EXECUTED = "EXECUTED"
STATUS_FAILED = "FAILED"
_BLOCKING = (STATUS_INTENDED, STATUS_EXECUTED)


class Play(NamedTuple):
    """Identity of one order in one sub-account for one detected play.

    ``key`` is the per-source row identity (the GUI_QUEUE KEY).
    ``split_key`` is the optional producer-agnostic *economic* identity
    (ticker|ratio|effective|policy). When set, the no-double-buy guard
    also blocks on it, so the same real split arriving via two
    producers (EDGAR + StockTitan) with different ``key``s still cannot
    be bought twice in the same sub-account. Empty -> legacy per-key
    behavior only (unchanged M1 semantics).
    """

    key: str
    broker: str
    account: str
    ticker: str
    action: str
    split_key: str = ""


def normalize_account(account: object) -> str:
    """Reduce an account number/mask to digits only.

    Brokers expose accounts inconsistently (full numbers vs ``****1234``
    masks); normalizing the stored value lets the ledger stay stable
    across runs for a given broker's own representation.
    """
    return re.sub(r"\D", "", str(account))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=30, check_same_thread=False)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                broker TEXT NOT NULL,
                sub_account TEXT NOT NULL,
                ticker TEXT NOT NULL,
                action TEXT NOT NULL,
                qty REAL NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                detail TEXT,
                UNIQUE(key, broker, sub_account, ticker, action)
            )
            """,
        )
        # Migrate older databases additively (M1 had no split_key; the
        # session-health work added an outcome reason code).
        cols = {r[1] for r in conn.execute("PRAGMA table_info(executions)")}
        if "split_key" not in cols:
            conn.execute(
                "ALTER TABLE executions ADD COLUMN split_key TEXT DEFAULT ''",
            )
        if "reason" not in cols:
            conn.execute(
                "ALTER TABLE executions ADD COLUMN reason TEXT DEFAULT ''",
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_exec_split "
            "ON executions(split_key, broker, sub_account, action)",
        )
        yield conn
        conn.commit()
    finally:
        conn.close()


def _norm(play: Play) -> tuple[str, str, str, str, str]:
    return (
        play.key,
        play.broker.lower(),
        normalize_account(play.account),
        play.ticker.upper(),
        play.action.lower(),
    )


def _row_status(conn: sqlite3.Connection, play: Play) -> str | None:
    cur = conn.execute(
        "SELECT status FROM executions "
        "WHERE key=? AND broker=? AND sub_account=? AND ticker=? AND action=?",
        _norm(play),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _economic_blocked(conn: sqlite3.Connection, play: Play) -> bool:
    """Return True if the same economic split is already done here.

    Producer-agnostic: matches on split_key + broker + sub_account +
    action regardless of the per-source ``key``. No-op when the caller
    didn't supply a split_key (legacy M1 behavior).
    """
    sk = (play.split_key or "").strip()
    if not sk:
        return False
    placeholders = ",".join("?" * len(_BLOCKING))
    cur = conn.execute(
        f"SELECT 1 FROM executions WHERE split_key=? AND broker=? "  # noqa: S608
        f"AND sub_account=? AND action=? AND status IN ({placeholders}) "
        f"LIMIT 1",
        (
            sk,
            play.broker.lower(),
            normalize_account(play.account),
            play.action.lower(),
            *_BLOCKING,
        ),
    )
    return cur.fetchone() is not None


def already_done(play: Play) -> bool:
    """Return True if this play was already executed or is mid-flight.

    Considers both the exact per-source key and the economic split key.
    Dry runs are never recorded, so they never block.
    """
    with _LOCK, _connect() as conn:
        return (
            _row_status(conn, play) in _BLOCKING
            or _economic_blocked(conn, play)
        )


def record_intent(play: Play, qty: float) -> bool:
    """Reserve this play before placing the order.

    Return ``False`` if it is already executed or mid-flight (the caller
    must then skip the order). Return ``True`` after writing/refreshing
    an ``INTENDED`` row. A prior ``FAILED`` row is reset to ``INTENDED``
    so a genuine retry is allowed.
    """
    with _LOCK, _connect() as conn:
        if _row_status(conn, play) in _BLOCKING or _economic_blocked(conn, play):
            return False
        now = _now()
        key, broker, acct, ticker, action = _norm(play)
        conn.execute(
            """
            INSERT INTO executions
                (key, broker, sub_account, ticker, action, qty,
                 status, created_at, updated_at, split_key)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(key, broker, sub_account, ticker, action)
            DO UPDATE SET status=excluded.status,
                          qty=excluded.qty,
                          updated_at=excluded.updated_at,
                          split_key=excluded.split_key
            """,
            (
                key,
                broker,
                acct,
                ticker,
                action,
                qty,
                STATUS_INTENDED,
                now,
                now,
                (play.split_key or "").strip(),
            ),
        )
        return True


def mark_result(play: Play, *, success: bool, detail: str = "") -> None:
    """Finalize a reserved play as EXECUTED or FAILED.

    The free-text ``detail`` is classified into a stable outcome reason
    code (src/outcomes) so a non-fill can be told apart: a benign
    stock-unavailable/restricted/market-closed result is not a
    session/tool failure, only SESSION_ERROR is.
    """
    from src.outcomes import classify_outcome  # noqa: PLC0415

    reason = classify_outcome(detail, success=success)
    with _LOCK, _connect() as conn:
        conn.execute(
            "UPDATE executions SET status=?, detail=?, reason=?, updated_at=? "
            "WHERE key=? AND broker=? AND sub_account=? AND ticker=? AND action=?",
            (
                STATUS_EXECUTED if success else STATUS_FAILED,
                detail[:500],
                reason,
                _now(),
                *_norm(play),
            ),
        )


def list_executions(key: str | None = None) -> list[dict[str, object]]:
    """Return ledger rows (optionally for one play key), newest first."""
    with _LOCK, _connect() as conn:
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM executions"
        params: tuple[str, ...] = ()
        if key is not None:
            sql += " WHERE key=?"
            params = (key,)
        sql += " ORDER BY updated_at DESC"
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def delete_row(row_id: int) -> bool:
    """Reset one play by its ledger row id (the GUI "reset this play").

    After this the play is treated as never attempted, so a future run
    (manual or signal) is free to execute it again. Returns True if a
    row was removed.
    """
    with _LOCK, _connect() as conn:
        cur = conn.execute("DELETE FROM executions WHERE id=?", (row_id,))
        return cur.rowcount > 0


def delete_play(play: Play) -> bool:
    """Reset one play by its identity tuple. Returns True if removed."""
    with _LOCK, _connect() as conn:
        cur = conn.execute(
            "DELETE FROM executions "
            "WHERE key=? AND broker=? AND sub_account=? AND ticker=? AND action=?",
            _norm(play),
        )
        return cur.rowcount > 0


def economic_done(split_key: str) -> bool:
    """Return True if this split was executed/in-flight in ANY account.

    Coarse, producer-agnostic check for dashboards/planning ("already
    captured somewhere"). The authoritative per-sub-account guard still
    runs at execution time via :func:`record_intent`.
    """
    sk = (split_key or "").strip()
    if not sk:
        return False
    placeholders = ",".join("?" * len(_BLOCKING))
    with _LOCK, _connect() as conn:
        cur = conn.execute(
            f"SELECT 1 FROM executions WHERE split_key=? "  # noqa: S608
            f"AND status IN ({placeholders}) LIMIT 1",
            (sk, *_BLOCKING),
        )
        return cur.fetchone() is not None


def clear_all() -> int:
    """Wipe the entire ledger. Returns the number of rows removed."""
    with _LOCK, _connect() as conn:
        cur = conn.execute("DELETE FROM executions")
        return cur.rowcount
