"""Ledger-vs-holdings reconciliation verdicts."""

from __future__ import annotations

from src import ledger
from src.gui.core import reconcile
from src.gui.core.reconcile import (
    MISSING,
    OK,
    ORPHAN,
    REVIEW_FILLED,
    REVIEW_MISSED,
    STALE,
    UNVERIFIABLE,
    reconcile as run_reconcile,
)

T0 = "2026-07-16T00:00:00+00:00"  # holdings capture
T_BEFORE = "2026-07-15T00:00:00+00:00"
T_AFTER = "2026-07-16T06:00:00+00:00"


def _row(broker, ticker, status, updated_at=T_BEFORE, action="buy", account="1"):
    return {
        "broker": broker, "ticker": ticker, "status": status,
        "action": action, "sub_account": account, "updated_at": updated_at,
    }


def _pos(broker, stock):
    return {"broker": broker, "stock": stock, "account": "1",
            "quantity": 1, "price": 1, "total": 1}


def _verdict(findings, ticker):
    for f in findings:
        if f.ticker == ticker:
            return f.verdict
    return None


def test_executed_held_is_ok():
    f = run_reconcile(
        [_row("bbae", "AAPL", ledger.STATUS_EXECUTED)],
        [_pos("bbae", "AAPL")],
        {"bbae": T0},
    )
    assert _verdict(f, "AAPL") == OK


def test_executed_not_held_is_missing():
    f = run_reconcile(
        [_row("bbae", "AAPL", ledger.STATUS_EXECUTED)],
        [],  # nothing held, but holdings ARE fresh for bbae
        {"bbae": T0},
    )
    assert _verdict(f, "AAPL") == MISSING


def test_stale_holdings_cannot_verify():
    # Holdings captured BEFORE the order -> can't conclude MISSING.
    f = run_reconcile(
        [_row("bbae", "AAPL", ledger.STATUS_EXECUTED, updated_at=T_AFTER)],
        [],
        {"bbae": T0},
    )
    assert _verdict(f, "AAPL") == STALE


def test_no_holdings_for_broker_unverifiable():
    f = run_reconcile(
        [_row("chase", "AAPL", ledger.STATUS_EXECUTED)],
        [],
        {},  # never pulled chase holdings
    )
    assert _verdict(f, "AAPL") == UNVERIFIABLE


def test_needs_review_held_vs_absent():
    held = run_reconcile(
        [_row("bbae", "AAPL", ledger.STATUS_NEEDS_REVIEW)],
        [_pos("bbae", "AAPL")], {"bbae": T0},
    )
    assert _verdict(held, "AAPL") == REVIEW_FILLED

    absent = run_reconcile(
        [_row("bbae", "AAPL", ledger.STATUS_NEEDS_REVIEW)],
        [], {"bbae": T0},
    )
    assert _verdict(absent, "AAPL") == REVIEW_MISSED


def test_orphan_position_flagged():
    f = run_reconcile([], [_pos("bbae", "TSLA")], {"bbae": T0})
    assert _verdict(f, "TSLA") == ORPHAN


def test_non_buy_and_failed_rows_ignored():
    rows = [
        _row("bbae", "AAPL", ledger.STATUS_FAILED),
        _row("bbae", "MSFT", ledger.STATUS_EXECUTED, action="sell"),
        _row("bbae", "NVDA", ledger.STATUS_INTENDED),
    ]
    f = run_reconcile(rows, [], {"bbae": T0})
    assert f == []


def test_worst_first_and_summary():
    rows = [
        _row("bbae", "AAA", ledger.STATUS_EXECUTED),  # missing (not held)
        _row("bbae", "BBB", ledger.STATUS_EXECUTED),  # ok (held)
    ]
    f = run_reconcile(rows, [_pos("bbae", "BBB")], {"bbae": T0})
    assert f[0].verdict == MISSING  # worst first
    summary = reconcile.summarize(f)
    assert summary[MISSING] == 1
    assert summary[OK] == 1
