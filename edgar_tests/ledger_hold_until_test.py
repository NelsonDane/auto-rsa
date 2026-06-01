"""Ledger hold_until + signal_type columns + due_for_sell helper (Phase 7)."""

from __future__ import annotations

import pytest

from src import ledger
from src.ledger import (
    Play,
    due_for_sell,
    list_executions,
    mark_result,
    record_intent,
)


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch, tmp_path):
    monkeypatch.setattr(ledger, "_DB_PATH", tmp_path / "ledger.db")
    yield


def test_play_defaults_for_back_compat():
    """Existing callers that build Play without the new fields keep
    working — defaults match the round-up flow's manual-sell semantic."""
    p = Play(key="K", broker="fidelity", account="111",
             ticker="X", action="buy")
    assert p.signal_type == "ROUND_UP_REVERSE"
    assert p.hold_until == ""


def test_record_intent_persists_signal_type_and_hold_until():
    p = Play(
        key="K1", broker="fidelity", account="2222",
        ticker="PRNT", action="buy",
        signal_type="SPIN_OFF", hold_until="2026-06-06",
    )
    assert record_intent(p, qty=1)
    (row,) = list_executions(key="K1")
    assert row["signal_type"] == "SPIN_OFF"
    assert row["hold_until"] == "2026-06-06"


def test_due_for_sell_finds_only_eligible_buys():
    """due_for_sell returns EXECUTED buys whose hold_until <= today,
    excludes manual-sell rows (hold_until=''), excludes ones already
    sold or with a sell in-flight."""
    # 1. Spin-off buy, hold_until passed, no sell yet -> eligible.
    spin = Play(
        key="SO-1", broker="fidelity", account="111",
        ticker="PRNT", action="buy",
        signal_type="SPIN_OFF", hold_until="2026-06-06",
    )
    record_intent(spin, qty=1)
    mark_result(spin, success=True, detail="")

    # 2. Round-up buy, no hold_until -> never eligible.
    round_up = Play(
        key="RU-1", broker="fidelity", account="111",
        ticker="ACME", action="buy",
        signal_type="ROUND_UP_REVERSE", hold_until="",
    )
    record_intent(round_up, qty=1)
    mark_result(round_up, success=True, detail="")

    # 3. Spin-off buy with hold_until in the future -> not eligible yet.
    future_spin = Play(
        key="SO-2", broker="fidelity", account="111",
        ticker="LATER", action="buy",
        signal_type="SPIN_OFF", hold_until="2099-01-01",
    )
    record_intent(future_spin, qty=1)
    mark_result(future_spin, success=True, detail="")

    # 4. Spin-off buy with hold_until passed BUT a sell already
    #    executed -> not eligible (avoid double-sell).
    sold_spin = Play(
        key="SO-3", broker="fidelity", account="111",
        ticker="SOLD", action="buy",
        signal_type="SPIN_OFF", hold_until="2026-06-06",
    )
    record_intent(sold_spin, qty=1)
    mark_result(sold_spin, success=True, detail="")
    sell = Play(
        key="SELL-3", broker="fidelity", account="111",
        ticker="SOLD", action="sell",
    )
    record_intent(sell, qty=1)
    mark_result(sell, success=True, detail="")

    due = due_for_sell(today_iso="2026-06-10")
    tickers = {r["ticker"] for r in due}
    assert tickers == {"PRNT"}


def test_due_for_sell_with_no_eligible_rows_returns_empty():
    assert due_for_sell(today_iso="2026-06-10") == []


def test_signal_type_normalized_to_upper_on_write():
    """Defensive — the producer always emits uppercase, but a hand-
    crafted Play with mixed case should normalize so downstream
    grouping by signal_type doesn't see duplicates."""
    p = Play(
        key="K-MIXED", broker="fidelity", account="333",
        ticker="X", action="buy",
        signal_type="spin_off",
    )
    record_intent(p, qty=1)
    (row,) = list_executions(key="K-MIXED")
    assert row["signal_type"] == "SPIN_OFF"


def test_schema_migration_adds_columns_to_pre_phase7_db(tmp_path, monkeypatch):
    """Existing pre-Phase-7 ledger.db files must accept the additive
    ALTER TABLE without losing data. Simulates the old schema by
    explicitly creating a table without signal_type / hold_until."""
    import sqlite3

    db_path = tmp_path / "old_ledger.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE executions (
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
    """)
    conn.execute(
        "INSERT INTO executions "
        "(key, broker, sub_account, ticker, action, qty, status, "
        " created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("OLD-K", "fidelity", "111", "OLD", "buy", 1.0, "EXECUTED",
         "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(ledger, "_DB_PATH", db_path)
    # Triggers _connect() which runs the migration.
    rows = list_executions(key="OLD-K")
    assert len(rows) == 1
    assert rows[0]["signal_type"] == "ROUND_UP_REVERSE"  # default backfill
    assert rows[0]["hold_until"] == ""
    # And new writes use the new columns.
    p = Play(
        key="NEW-K", broker="fidelity", account="111", ticker="NEW",
        action="buy", signal_type="SPIN_OFF", hold_until="2026-06-06",
    )
    record_intent(p, qty=1)
    (new_row,) = list_executions(key="NEW-K")
    assert new_row["signal_type"] == "SPIN_OFF"
    assert new_row["hold_until"] == "2026-06-06"
