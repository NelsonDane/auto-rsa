"""M5 phase-1 shadow: planning + entrypoint (no orders, fully mocked)."""

from src.autoexec import __main__ as ax_main
from src.autoexec import shadow
from src.autoexec.shadow import build_shadow, parse_account_filter
from src.gui.core.sheets import Signal


def _sig(ticker, policy, conf, *, key=None, ratio="1-for-30",
         eff="December 1, 2099"):
    """Default effective_date is far in the future so plan_signals
    doesn't skip on past-date regardless of wall-clock time."""
    return Signal(
        created_at="2026-05-17", ticker=ticker, action="buy", ratio=ratio,
        effective_date=eff, presplit_deadline="",
        fractional_policy=policy, confidence=str(conf), source="SEC_EFTS",
        key=key or f"K-{ticker}", status="PENDING",
    )


def test_parse_account_filter():
    assert parse_account_filter("") == {}
    assert parse_account_filter("not json") == {}
    assert parse_account_filter('{"fidelity":["7743","1468"]}') == {
        "fidelity": ["7743", "1468"],
    }


def test_build_shadow_partitions_and_targets():
    sigs = [
        _sig("ACME", "ROUND_UP", 0.93),
        _sig("CASHCO", "CASH_IN_LIEU", 0.96),
        _sig("DONE", "ROUND_UP", 0.93),
    ]
    items = build_shadow(
        sigs,
        broker_keys=["fidelity", "robinhood"],
        account_filter={"fidelity": ["7743"], "robinhood": []},
        is_done=lambda sk: sk.startswith("DONE|"),
    )
    by = {i.ticker: i for i in items}
    assert by["ACME"].decision == "WOULD_BUY"
    assert by["ACME"].broker_targets == ["fidelity(1 acct)", "robinhood(filter:none)"]
    assert by["CASHCO"].decision == "SKIP" and "ROUND_UP" in by["CASHCO"].reason
    assert by["DONE"].decision == "SKIP" and "already executed" in by["DONE"].reason
    rpt = shadow.render_report(items)
    assert "WOULD BUY 1 ACME" in rpt and "no orders placed" in rpt


def test_entrypoint_kill_switch(monkeypatch):
    monkeypatch.setenv("RSA_AUTO_DISABLED", "1")
    # Must no-op without even needing sheet config.
    assert ax_main.main([]) == 0


def test_entrypoint_requires_config(monkeypatch):
    monkeypatch.delenv("RSA_AUTO_DISABLED", raising=False)
    monkeypatch.setattr(ax_main, "_KILL_FILE",
                        ax_main._KILL_FILE.parent / "nope")
    monkeypatch.delenv("RSA_SHEETS_SA_JSON", raising=False)
    monkeypatch.delenv("RSA_SHEETS_ID", raising=False)
    assert ax_main.main([]) == 2


def test_entrypoint_happy_path_no_orders(monkeypatch, capsys):
    monkeypatch.delenv("RSA_AUTO_DISABLED", raising=False)
    monkeypatch.setattr(ax_main, "_KILL_FILE",
                        ax_main._KILL_FILE.parent / "nope")
    monkeypatch.setenv("RSA_SHEETS_SA_JSON", "{}")
    monkeypatch.setenv("RSA_SHEETS_ID", "SHEET")
    monkeypatch.setenv("RSA_AUTO_BROKERS", "fidelity")
    monkeypatch.setattr(
        ax_main, "fetch_signals",
        lambda *a, **k: [_sig("ACME", "ROUND_UP", 0.93)],
    )
    monkeypatch.setattr(ax_main.ledger, "economic_done",
                        lambda _sk: False)
    rc = ax_main.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "WOULD BUY 1 ACME" in out
