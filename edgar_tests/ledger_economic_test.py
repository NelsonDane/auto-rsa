"""Economic (split_key) cross-producer double-buy guard + M1 parity."""

import sqlite3
from pathlib import Path

import pytest

from src import ledger
from src.ledger import (
    Play,
    already_done,
    delete_play,
    mark_result,
    record_intent,
)


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "_DB_PATH", tmp_path / "ledger.db")


def test_legacy_behavior_unchanged_without_split_key():
    p = Play("K1", "fidelity", "Z-7743", "ABCD", "buy")
    assert record_intent(p, 1) is True
    assert record_intent(p, 1) is False  # same key blocks (M1)
    # A different key, no split_key -> independent (legacy semantics).
    assert record_intent(Play("K2", "fidelity", "Z-7743", "ABCD", "buy"), 1) is True


def test_economic_block_across_producers():
    sk = "LCID|1-FOR-40|JUNE 1, 2026|ROUND_UP"
    edgar = Play("EDGAR:1", "fidelity", "Z-7743", "LCID", "buy", sk)
    titan = Play("TITAN:9", "fidelity", "Z-7743", "LCID", "buy", sk)

    assert record_intent(edgar, 1) is True
    mark_result(edgar, success=True)
    # Same economic split, different source KEY, same sub-account -> blocked.
    assert already_done(titan) is True
    assert record_intent(titan, 1) is False


def test_economic_block_while_in_flight():
    sk = "ACME|1-FOR-10|X|ROUND_UP"
    a = Play("A", "fidelity", "111", "ACME", "buy", sk)
    b = Play("B", "fidelity", "111", "ACME", "buy", sk)
    assert record_intent(a, 1) is True  # INTENDED, not yet resolved
    assert record_intent(b, 1) is False  # mid-flight sibling blocks


def test_other_account_not_blocked():
    sk = "ACME|1-FOR-10|X|ROUND_UP"
    assert record_intent(Play("A", "fidelity", "111", "ACME", "buy", sk), 1) is True
    mark_result(Play("A", "fidelity", "111", "ACME", "buy", sk), success=True)
    # Different sub-account: the play still needs to run there.
    assert record_intent(Play("B", "fidelity", "222", "ACME", "buy", sk), 1) is True


def test_failed_is_retryable_economically():
    sk = "ACME|1-FOR-10|X|ROUND_UP"
    a = Play("A", "fidelity", "111", "ACME", "buy", sk)
    assert record_intent(a, 1) is True
    mark_result(a, success=False)  # FAILED is not blocking
    assert already_done(a) is False
    assert record_intent(Play("B", "fidelity", "111", "ACME", "buy", sk), 1) is True


def test_delete_play_frees_economic():
    sk = "ACME|1-FOR-10|X|ROUND_UP"
    a = Play("A", "fidelity", "111", "ACME", "buy", sk)
    assert record_intent(a, 1) is True
    mark_result(a, success=True)
    assert delete_play(a) is True
    assert record_intent(Play("B", "fidelity", "111", "ACME", "buy", sk), 1) is True


def test_migration_from_pre_split_key_schema(tmp_path, monkeypatch):
    db = tmp_path / "old.db"
    monkeypatch.setattr(ledger, "_DB_PATH", db)
    # Simulate an M1-era DB with no split_key column + an EXECUTED row.
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL, broker TEXT NOT NULL, sub_account TEXT NOT NULL,
            ticker TEXT NOT NULL, action TEXT NOT NULL, qty REAL NOT NULL,
            status TEXT NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, detail TEXT,
            UNIQUE(key, broker, sub_account, ticker, action))""",
    )
    conn.execute(
        "INSERT INTO executions (key,broker,sub_account,ticker,action,qty,"
        "status,created_at,updated_at) VALUES "
        "('OLD','fidelity','7743','ABCD','buy',1,'EXECUTED','t','t')",
    )
    conn.commit()
    conn.close()

    # Column is added on first connect; the legacy row still blocks by key.
    assert already_done(Play("OLD", "fidelity", "7743", "ABCD", "buy")) is True
    cols = {
        r[1]
        for r in sqlite3.connect(db).execute("PRAGMA table_info(executions)")
    }
    assert "split_key" in cols
    # New economic guard works on the migrated DB.
    sk = "NEW|1-FOR-5|Y|ROUND_UP"
    assert record_intent(Play("N1", "fidelity", "9", "NEW", "buy", sk), 1) is True
    assert record_intent(Play("N2", "fidelity", "9", "NEW", "buy", sk), 1) is False


def test_db_path_is_patched():
    assert isinstance(ledger._DB_PATH, Path)
