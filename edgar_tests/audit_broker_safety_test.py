"""Tests for scripts/audit_broker_safety.py — the C1/C2 detector."""

from __future__ import annotations

import textwrap
from pathlib import Path

from scripts import audit_broker_safety as audit


def _write_module(tmp_path: Path, name: str, body: str) -> Path:
    """Drop a synthetic broker module under <tmp>/src/brokerages/."""
    bdir = tmp_path / "src" / "brokerages"
    bdir.mkdir(parents=True, exist_ok=True)
    p = bdir / name
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


# --- direct audit_file behavior ---------------------------------------

def test_fidelity_real_module_passes_both_checks():
    """The reference implementation must satisfy both guards."""
    repo = Path(__file__).resolve().parents[1]
    fid = repo / "src" / "brokerages" / "fidelity_api.py"
    broker, findings = audit.audit_file(fid)
    assert broker == "fidelity"
    assert findings == [], (
        "Fidelity is the canonical safe pattern — if this fails, "
        "EITHER the audit logic broke or the Fidelity guards were removed. "
        f"Findings: {findings}"
    )


def test_broker_missing_both_guards_fails_both_checks(tmp_path):
    _write_module(tmp_path, "fake_api.py", """
        from src.helper_api import Brokerage, StockOrder

        def fake_transaction(obj, order_obj, loop=None):
            for account in obj.get_accounts():
                obj.place_order(symbol="X", quantity=1)
    """)
    broker, findings = audit.audit_file(
        tmp_path / "src" / "brokerages" / "fake_api.py",
    )
    assert broker == "fake"
    assert len(findings) == 2
    assert any("C1 ledger" in f for f in findings)
    assert any("C2 filter" in f for f in findings)


def test_broker_with_both_guards_passes(tmp_path):
    _write_module(tmp_path, "safe_api.py", """
        from src.helper_api import account_allowed
        from src.ledger import Play, mark_result, record_intent

        def safe_transaction(obj, order_obj, loop=None):
            for account in obj.get_accounts():
                if not account_allowed("safe", account, order_obj.get_action()):
                    continue
                play = Play(key="K", broker="safe", account=account,
                            ticker="X", action="buy")
                if not record_intent(play, 1):
                    continue
                success = obj.place_order(symbol="X", quantity=1)
                mark_result(play, success=success, detail="")
    """)
    _, findings = audit.audit_file(
        tmp_path / "src" / "brokerages" / "safe_api.py",
    )
    assert findings == []


def test_partial_guard_still_flags_the_missing_one(tmp_path):
    """A broker that calls account_allowed but skips record_intent
    is still unsafe — must flag the missing piece, not silently pass."""
    _write_module(tmp_path, "half_api.py", """
        from src.helper_api import account_allowed

        def half_transaction(obj, order_obj, loop=None):
            for account in obj.get_accounts():
                if not account_allowed("half", account, "buy"):
                    continue
                obj.place_order(symbol="X")
    """)
    _, findings = audit.audit_file(
        tmp_path / "src" / "brokerages" / "half_api.py",
    )
    assert len(findings) == 1
    assert "C1 ledger" in findings[0]
    assert "C2 filter" not in findings[0]


def test_method_attribute_call_is_recognised(tmp_path):
    """Catches `self.something.record_intent(...)` not just bare names."""
    _write_module(tmp_path, "attr_api.py", """
        def attr_transaction(obj, order_obj, loop=None):
            for account in obj.get_accounts():
                if not obj.helpers.account_allowed("attr", account, "buy"):
                    continue
                play = obj.ledger.record_intent(account)
                obj.place_order()
                obj.ledger.mark_result(play, success=True)
    """)
    _, findings = audit.audit_file(
        tmp_path / "src" / "brokerages" / "attr_api.py",
    )
    assert findings == []


def test_no_transaction_function_is_not_flagged(tmp_path):
    """Holdings-only or non-conforming module shouldn't fail audit —
    it can't place orders so the guards are moot."""
    _write_module(tmp_path, "noop_api.py", """
        def noop_holdings(obj, loop=None):
            obj.fetch()
    """)
    _, findings = audit.audit_file(
        tmp_path / "src" / "brokerages" / "noop_api.py",
    )
    assert findings == []


def test_underscore_prefixed_files_are_skipped(tmp_path):
    """`_*` modules are patch helpers, not broker integrations."""
    _write_module(tmp_path, "_patch_api.py", """
        def _patch_transaction(obj, order_obj, loop=None):
            obj.place_order()  # would fail audit if not skipped
    """)
    code, results = audit.audit_repo(tmp_path)
    assert results == []  # _patch_api.py filtered out by _is_broker_module
    assert code == 0


def test_file_function_prefix_mismatch_is_caught(tmp_path):
    """`tasty_api.py` defines `tastytrade_transaction` — the fallback
    must catch it instead of silently passing."""
    _write_module(tmp_path, "tasty_api.py", """
        def tastytrade_transaction(obj, order_obj, loop=None):
            obj.place_order()
    """)
    broker, findings = audit.audit_file(
        tmp_path / "src" / "brokerages" / "tasty_api.py",
    )
    assert broker == "tasty"
    assert len(findings) == 2  # both guards missing


def test_async_transaction_function_is_audited(tmp_path):
    _write_module(tmp_path, "async_api.py", """
        async def async_transaction(obj, order_obj, loop=None):
            obj.place_order()
    """)
    _, findings = audit.audit_file(
        tmp_path / "src" / "brokerages" / "async_api.py",
    )
    assert len(findings) == 2


def test_exemption_dict_short_circuits_a_check(tmp_path, monkeypatch):
    """Operator-tracked exemption opts a broker out of a specific check."""
    _write_module(tmp_path, "legacy_api.py", """
        def legacy_transaction(obj, order_obj, loop=None):
            obj.place_order()
    """)
    monkeypatch.setitem(
        audit.EXEMPT_LEDGER, "legacy",
        "Test: pretend this broker is ledger-exempt",
    )
    _, findings = audit.audit_file(
        tmp_path / "src" / "brokerages" / "legacy_api.py",
    )
    # Only C2 should fire now (C1 exempted).
    assert len(findings) == 1
    assert "C2 filter" in findings[0]


# --- repo-level behavior ---------------------------------------------

def test_real_repo_audit_currently_fails_on_known_gap():
    """Locks in the known baseline (audit C1/C2): every broker except
    Fidelity is missing guards. If this passes, either the bug was
    fixed (great — update this test) or the audit logic broke (bad)."""
    repo = Path(__file__).resolve().parents[1]
    code, results = audit.audit_repo(repo)
    failing_brokers = {b for b, f in results if f}
    # Locked baseline: Fidelity passes; everyone else fails.
    assert code == 1
    assert "fidelity" not in failing_brokers
    # Spot-check a few we know are unguarded (whole list is fine too).
    for expected in ("bbae", "chase", "public", "robinhood", "schwab",
                     "wellsfargo", "tasty"):
        assert expected in failing_brokers, (
            f"{expected} should be flagged until C1/C2 are fixed for it"
        )


def test_main_returns_nonzero_when_findings_exist():
    """Exit code wiring so CI can gate on this script."""
    assert audit.main() == 1
