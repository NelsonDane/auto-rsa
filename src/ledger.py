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
# Ambiguous outcome: intent was already recorded (the order was being
# placed) and then the session/browser broke, so we DON'T KNOW whether
# the order reached the broker. Auto-retrying risks a double-buy, so this
# is blocking like INTENDED/EXECUTED — a human must verify with the
# broker and reset the row on the Ledger tab. (A missed buy beats a
# double-buy for real money.)
STATUS_NEEDS_REVIEW = "NEEDS_REVIEW"
# Accepted and working at the broker (queued/confirmed) but not yet
# filled. It MIGHT still fill, so auto-retrying risks a double-buy —
# blocking like INTENDED/EXECUTED/NEEDS_REVIEW. Distinct from FAILED:
# a rejected/never-placed order is FAILED (safe to retry), a working
# order is PENDING (must be verified, not blindly re-fired). See
# docs/FILL_VERIFICATION_DESIGN.md §5.
STATUS_PENDING = "PENDING"
_BLOCKING = (
    STATUS_INTENDED,
    STATUS_EXECUTED,
    STATUS_NEEDS_REVIEW,
    STATUS_PENDING,
)


class Play(NamedTuple):
    """Identity of one order in one sub-account for one detected play.

    ``key`` is the per-source row identity (the GUI_QUEUE KEY).
    ``split_key`` is the optional producer-agnostic *economic* identity
    (ticker|ratio|effective|policy). When set, the no-double-buy guard
    also blocks on it, so the same real split arriving via two
    producers (EDGAR + StockTitan) with different ``key``s still cannot
    be bought twice in the same sub-account. Empty -> legacy per-key
    behavior only (unchanged M1 semantics).

    Phase 7 additions:

    * ``signal_type`` carries the originating event class so the
      per-signal-type dashboard can group ledger history by alert
      kind. Defaults to ``ROUND_UP_REVERSE`` for back-compat with
      pre-Phase-5 callers.
    * ``hold_until`` is the ISO date (YYYY-MM-DD) on/after which an
      auto-sell job (Phase 8) may sell this position. Empty string
      means "manual sell only" — the round-up flow keeps that
      semantic. Spin-offs and special divs supply a real date.
    """

    key: str
    broker: str
    account: str
    ticker: str
    action: str
    split_key: str = ""
    signal_type: str = "ROUND_UP_REVERSE"
    hold_until: str = ""


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
        # session-health work added an outcome reason code; Phase 7
        # adds signal_type + hold_until for the per-type dashboard and
        # the future auto-sell job).
        cols = {r[1] for r in conn.execute("PRAGMA table_info(executions)")}
        if "split_key" not in cols:
            conn.execute(
                "ALTER TABLE executions ADD COLUMN split_key TEXT DEFAULT ''",
            )
        if "reason" not in cols:
            conn.execute(
                "ALTER TABLE executions ADD COLUMN reason TEXT DEFAULT ''",
            )
        if "signal_type" not in cols:
            conn.execute(
                "ALTER TABLE executions ADD COLUMN signal_type TEXT "
                "DEFAULT 'ROUND_UP_REVERSE'",
            )
        if "hold_until" not in cols:
            conn.execute(
                "ALTER TABLE executions ADD COLUMN hold_until TEXT DEFAULT ''",
            )
        # Fill-verification columns (docs/FILL_VERIFICATION_DESIGN.md §5):
        # the broker order id, the last known FillState, the quantity the
        # broker reported filled, when it was last verified, and how
        # (inline / poll / reconcile). All nullable so old rows read fine.
        if "order_ref" not in cols:
            conn.execute(
                "ALTER TABLE executions ADD COLUMN order_ref TEXT DEFAULT ''",
            )
        if "fill_state" not in cols:
            conn.execute(
                "ALTER TABLE executions ADD COLUMN fill_state TEXT DEFAULT ''",
            )
        if "filled_qty" not in cols:
            conn.execute(
                "ALTER TABLE executions ADD COLUMN filled_qty REAL",
            )
        if "verified_at" not in cols:
            conn.execute(
                "ALTER TABLE executions ADD COLUMN verified_at TEXT DEFAULT ''",
            )
        if "verify_source" not in cols:
            conn.execute(
                "ALTER TABLE executions ADD COLUMN verify_source TEXT DEFAULT ''",
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_exec_split "
            "ON executions(split_key, broker, sub_account, action)",
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_exec_hold "
            "ON executions(hold_until, status)",
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
                 status, created_at, updated_at, split_key,
                 signal_type, hold_until)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(key, broker, sub_account, ticker, action)
            DO UPDATE SET status=excluded.status,
                          qty=excluded.qty,
                          updated_at=excluded.updated_at,
                          split_key=excluded.split_key,
                          signal_type=excluded.signal_type,
                          hold_until=excluded.hold_until
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
                (play.signal_type or "ROUND_UP_REVERSE").upper(),
                (play.hold_until or "").strip(),
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
    from src.outcomes import SESSION_ERROR, classify_outcome  # noqa: PLC0415

    reason = classify_outcome(detail, success=success)
    if success:
        status = STATUS_EXECUTED
    elif reason == SESSION_ERROR:
        # Intent was recorded before the order was placed, so a session
        # break here is ambiguous: the order may already be live. Do NOT
        # mark it retryable FAILED (which record_intent would reset to
        # INTENDED and re-buy) — flag it for human review instead.
        status = STATUS_NEEDS_REVIEW
    else:
        status = STATUS_FAILED
    with _LOCK, _connect() as conn:
        conn.execute(
            "UPDATE executions SET status=?, detail=?, reason=?, updated_at=? "
            "WHERE key=? AND broker=? AND sub_account=? AND ticker=? AND action=?",
            (
                status,
                detail[:500],
                reason,
                _now(),
                *_norm(play),
            ),
        )


def mark_fill(
    play: Play,
    result: object,
    *,
    source: str = "inline",
) -> str:
    """Finalize a reserved play from a verified fill outcome.

    ``result`` is a :class:`src.brokerages.fill_result.FillResult` (duck
    -typed: any object exposing ``state``/``qty``/``order_ref``/``detail``).
    The :class:`~src.brokerages.fill_result.FillState` maps to exactly
    one ledger status here — the single decision site so "pending is not
    filled" can never be re-decided elsewhere:

    * FILLED   → EXECUTED   (the only path to EXECUTED via a fill)
    * PENDING  → PENDING    (accepted/working; blocking, not a fill)
    * REJECTED → FAILED     (never placed / refused; safe to retry)
    * UNKNOWN  → NEEDS_REVIEW (ambiguous; human verifies)

    Returns the ledger status written. Records the broker order id,
    the FillState, the reported fill quantity, and the verification
    source/timestamp alongside the row. ``mark_result`` remains the
    coarse (success/fail) entry point for brokers not yet fill-aware.
    """
    from src.brokerages.fill_result import FillState  # noqa: PLC0415
    from src.outcomes import OK, classify_outcome  # noqa: PLC0415

    state = getattr(result, "state", None)
    detail = str(getattr(result, "detail", "") or "")
    order_ref = str(getattr(result, "order_ref", "") or "")
    filled_qty = getattr(result, "qty", None)

    status_by_state = {
        FillState.FILLED: STATUS_EXECUTED,
        FillState.PENDING: STATUS_PENDING,
        FillState.REJECTED: STATUS_FAILED,
        FillState.UNKNOWN: STATUS_NEEDS_REVIEW,
    }
    # Unrecognized/missing state is treated as UNKNOWN — the safe,
    # non-fill default (a missed buy beats a double-buy).
    status = status_by_state.get(state, STATUS_NEEDS_REVIEW)  # type: ignore[arg-type]
    # A genuine fill is OK; everything else keeps a classified reason so
    # the session panel / availability matrix can tell a benign non-fill
    # (stock unavailable) from real session breakage.
    reason = OK if status == STATUS_EXECUTED else classify_outcome(detail, success=False)

    with _LOCK, _connect() as conn:
        conn.execute(
            "UPDATE executions SET status=?, detail=?, reason=?, updated_at=?, "
            "order_ref=?, fill_state=?, filled_qty=?, verified_at=?, "
            "verify_source=? "
            "WHERE key=? AND broker=? AND sub_account=? AND ticker=? AND action=?",
            (
                status,
                detail[:500],
                reason,
                _now(),
                order_ref,
                getattr(state, "value", "") if state is not None else "",
                filled_qty,
                _now(),
                str(source or ""),
                *_norm(play),
            ),
        )
    return status


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


def due_for_sell(today_iso: str) -> list[dict[str, object]]:
    """Return EXECUTED buy rows whose hold_until is on/before ``today_iso``.

    The Phase 8 auto-sell job reads this to decide which positions
    can be sold today. Excludes rows that have no hold_until set
    (the round-up flow defaults to manual sell). Excludes rows for
    tickers where an EXECUTED or INTENDED SELL already exists in
    the same (broker, account) — that's a sell-already-placed guard.
    """
    # Parse dates instead of comparing ISO strings lexicographically: a
    # non-ISO hold_until ("January 5, 2026", "1/5/2026", "2026-1-5")
    # sorts wrong as a string and could surface a position as due before
    # its real hold date — selling too early. Anything unparseable is
    # skipped rather than risk an early sell.
    from src.edgar.market_calendar import parse_effective_date  # noqa: PLC0415

    today = parse_effective_date(today_iso)
    if today is None:
        return []
    with _LOCK, _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM executions
            WHERE action='buy'
              AND status=?
              AND hold_until != ''
            """,
            (STATUS_EXECUTED,),
        ).fetchall()
        if not rows:
            return []
        out: list[dict[str, object]] = []
        for r in rows:
            hold = parse_effective_date(r["hold_until"])
            if hold is None or hold > today:
                continue
            # Guard: any concurrent SELL for the same broker/account/ticker
            # blocks a duplicate auto-sell.
            sell_row = conn.execute(
                "SELECT 1 FROM executions WHERE broker=? AND sub_account=? "
                "AND ticker=? AND action='sell' AND status IN (?,?) LIMIT 1",
                (r["broker"], r["sub_account"], r["ticker"],
                 STATUS_INTENDED, STATUS_EXECUTED),
            ).fetchone()
            if sell_row is None:
                out.append(dict(r))
        return out


def delete_row(row_id: int) -> bool:
    """Reset one play by its ledger row id (the GUI "reset this play").

    After this the play is treated as never attempted, so a future run
    (manual or signal) is free to execute it again. Returns True if a
    row was removed.
    """
    with _LOCK, _connect() as conn:
        cur = conn.execute("DELETE FROM executions WHERE id=?", (row_id,))
        return cur.rowcount > 0


def delete_by_ticker(ticker: str) -> int:
    """Reset EVERY ledger row for one ticker (all accounts/brokers).

    The GUI "reset by ticker" — so a stock you want to buy again (or that
    reverse-splits a second time) can be freed in one action instead of
    resetting each account row by hand. Returns the number of rows removed.
    """
    t = str(ticker).strip().upper()
    if not t:
        return 0
    with _LOCK, _connect() as conn:
        cur = conn.execute("DELETE FROM executions WHERE UPPER(ticker)=?", (t,))
        return cur.rowcount


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
