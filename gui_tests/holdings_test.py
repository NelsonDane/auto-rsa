"""Structured holdings capture, storage (merge-per-broker), aggregation."""

from __future__ import annotations

import pytest

from src.gui.core import holdings as h
from src.gui.core import runner as runner_mod
from src.gui.core.engine_proc import HOLDINGS_SENTINEL
from src.gui.core.runner import RunStatus, TradeRunner
from src.gui.core.vault import Vault


@pytest.fixture(autouse=True)
def _tmp_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "HOLDINGS_PATH", tmp_path / "hold.json")


def test_parse_line_valid_and_invalid():
    p = h.parse_line("bbae\tBBAE 1\t12345\taapl\t2.0\t150.0\t300.0")
    assert p == {
        "broker": "bbae", "parent": "BBAE 1", "account": "12345",
        "stock": "AAPL", "quantity": 2.0, "price": 150.0, "total": 300.0,
    }
    assert h.parse_line("too\tfew\tfields") is None
    assert h.parse_line("bbae\tp\ta\t\t1\t2\t2") is None  # empty stock
    assert h.parse_line("bbae\tp\ta\tX\tNaNq\t2\t2") is None  # bad number


def test_save_merges_per_broker():
    h.save_positions(
        [h.parse_line("bbae\tB\t1\tAAPL\t2\t150\t300")],
        captured_at="2026-07-16T00:00:00",
    )
    h.save_positions(
        [h.parse_line("fennel\tF\t9\tTSLA\t1\t200\t200")],
        captured_at="2026-07-16T00:01:00",
    )
    snap = h.load_snapshot()
    assert sorted(p["stock"] for p in snap["positions"]) == ["AAPL", "TSLA"]
    assert set(snap["captured_at"]) == {"bbae", "fennel"}

    # Re-pulling bbae REPLACES its rows (doesn't duplicate) and keeps fennel.
    h.save_positions(
        [h.parse_line("bbae\tB\t1\tNVDA\t1\t500\t500")],
        captured_at="2026-07-16T00:05:00",
    )
    snap = h.load_snapshot()
    bbae = [p for p in snap["positions"] if p["broker"] == "bbae"]
    assert [p["stock"] for p in bbae] == ["NVDA"]  # AAPL replaced
    assert any(p["broker"] == "fennel" for p in snap["positions"])  # kept


def test_empty_save_never_wipes():
    h.save_positions(
        [h.parse_line("bbae\tB\t1\tAAPL\t2\t150\t300")],
        captured_at="2026-07-16T00:00:00",
    )
    h.save_positions([], captured_at="2026-07-16T09:00:00")  # trade run, no holdings
    assert h.load_snapshot()["positions"], "empty save must not wipe the snapshot"


def test_aggregate_by_ticker():
    positions = [
        h.parse_line("bbae\tB\t1\tAAPL\t2\t150\t300"),
        h.parse_line("fennel\tF\t9\tAAPL\t1\t150\t150"),
        h.parse_line("bbae\tB\t2\tTSLA\t1\t200\t200"),
    ]
    rows = h.aggregate_by_ticker(positions)
    assert rows[0]["stock"] == "AAPL"  # highest value first
    assert rows[0]["quantity"] == 3.0
    assert rows[0]["value"] == 450.0
    assert rows[0]["brokers"] == 2


def test_clear_snapshot():
    h.save_positions(
        [h.parse_line("bbae\tB\t1\tAAPL\t2\t150\t300")],
        captured_at="x",
    )
    h.clear_snapshot()
    assert h.load_snapshot()["positions"] == []


class _FakePumpProc:
    """A finished engine process whose stdout replays fixed lines."""

    def __init__(self, lines):
        self.stdout = iter(lines)
        self.stdin = None
        self.pid = 999_999_999
        self.returncode = 0

    def wait(self):
        return 0

    def poll(self):
        return 0


def test_pump_captures_holdings_sentinels(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "_RUN_LOCK", tmp_path / "run.lock")
    v = Vault(tmp_path / "v.json")
    v.initialize("pw")
    r = TradeRunner(v)
    monkeypatch.setattr(r, "_write_audit_log", lambda _s: None)
    monkeypatch.setattr(r, "_notify", lambda _s: None)
    r._status = RunStatus.RUNNING
    r._proc = _FakePumpProc([
        f"{HOLDINGS_SENTINEL}bbae\tBBAE 1\t123\tAAPL\t2.0\t150.0\t300.0\n",
        "a normal broker log line\n",
        f"{HOLDINGS_SENTINEL}bbae\tBBAE 1\t123\tMSFT\t1\t400\t400\n",
        "garbled\x00RSA_HOLD\x00broken line\n",  # malformed -> skipped, no crash
    ])
    r._pump()
    snap = h.load_snapshot()
    assert sorted(p["stock"] for p in snap["positions"]) == ["AAPL", "MSFT"]
