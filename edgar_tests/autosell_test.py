"""Auto-sell finder + CLI (Phase 8)."""

from __future__ import annotations

import pytest

from src import ledger
from src.autosell import find_due_sells
from src.autosell.finder import summary_text
from src.ledger import Play, mark_result, record_intent


@pytest.fixture(autouse=True)
def _isolated_ledger(monkeypatch, tmp_path):
    monkeypatch.setattr(ledger, "_DB_PATH", tmp_path / "ledger.db")


def _seed_buy(
    *, ticker: str, hold_until: str, signal_type: str,
    broker: str = "fidelity", account: str = "111", key: str = "K",
) -> None:
    p = Play(
        key=key, broker=broker, account=account, ticker=ticker,
        action="buy", signal_type=signal_type, hold_until=hold_until,
    )
    record_intent(p, qty=1)
    mark_result(p, success=True, detail="")


def test_find_due_sells_returns_eligible_rows():
    _seed_buy(
        ticker="PRNT", hold_until="2026-06-06",
        signal_type="SPIN_OFF", key="SO-1",
    )
    out = find_due_sells(today_iso="2026-06-10")
    assert len(out) == 1
    assert out[0].ticker == "PRNT"
    assert out[0].signal_type == "SPIN_OFF"
    assert out[0].qty == 1.0
    assert out[0].hold_until == "2026-06-06"


def test_find_due_sells_excludes_future_dates():
    _seed_buy(
        ticker="LATER", hold_until="2099-01-01",
        signal_type="SPIN_OFF", key="SO-FUT",
    )
    out = find_due_sells(today_iso="2026-06-10")
    assert out == []


def test_find_due_sells_excludes_round_ups_without_hold_until():
    _seed_buy(
        ticker="ACME", hold_until="", signal_type="ROUND_UP_REVERSE",
        key="RU-1",
    )
    out = find_due_sells(today_iso="2026-06-10")
    assert out == []


def test_summary_text_zero():
    assert "0 positions due" in summary_text([])


def test_summary_text_groups_by_broker():
    _seed_buy(
        ticker="A", hold_until="2026-06-06",
        signal_type="SPIN_OFF", broker="fidelity", account="111",
        key="A",
    )
    _seed_buy(
        ticker="B", hold_until="2026-06-06",
        signal_type="SPIN_OFF", broker="fidelity", account="222",
        key="B",
    )
    _seed_buy(
        ticker="C", hold_until="2026-06-06",
        signal_type="SPECIAL_DIV", broker="public", account="333",
        key="C",
    )
    out = find_due_sells(today_iso="2026-06-10")
    text = summary_text(out)
    assert "3 position(s) due" in text
    assert "fidelity=2" in text
    assert "public=1" in text


def test_cli_returns_zero_on_success(monkeypatch, capsys):
    """The launchd job's exit code drives whether the operator sees
    a failure email from launchd. 0 = ran cleanly even if nothing
    was due (silent days are normal)."""
    from src.autosell import __main__ as cli

    monkeypatch.delenv("RSA_NOTIFY_WEBHOOK", raising=False)
    rc = cli.main()
    assert rc == 0
    # Stdout includes the summary line.
    captured = capsys.readouterr()
    assert "AutoRSA" in captured.out


def test_cli_returns_nonzero_on_ledger_failure(monkeypatch, capsys):
    """A real I/O error should surface to launchd so the operator
    sees the failure email."""
    from src.autosell import __main__ as cli

    def _boom(*_a, **_k):
        msg = "ledger db unreadable"
        raise RuntimeError(msg)

    monkeypatch.setattr(cli, "find_due_sells", _boom)
    rc = cli.main()
    assert rc == 1
    err = capsys.readouterr().err
    assert "AutoRSA auto-sell finder failed" in err
