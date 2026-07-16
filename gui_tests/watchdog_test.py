"""Render-trace + hang-watchdog diagnostics."""

from __future__ import annotations

import pytest

from src.gui.core import watchdog as w


@pytest.fixture(autouse=True)
def _tmp_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "TRACE_PATH", tmp_path / "trace.log")
    monkeypatch.setattr(w, "HANG_DUMP_PATH", tmp_path / "hang.log")
    monkeypatch.setattr(w, "_CREDS", tmp_path)
    monkeypatch.setattr(w, "_hang_file", None)
    yield
    w.disarm()
    monkeypatch.setattr(w, "_hang_file", None)


def test_trace_records_sections_and_completion():
    w.begin_run()
    w.mark("sidebar")
    w.mark("Trade tab")
    assert w.last_run_completed() is False  # not finished yet
    w.end_run()
    trace = w.read_trace()
    assert "sidebar" in trace
    assert "Trade tab" in trace
    assert w.last_run_completed() is True


def test_incomplete_run_leaves_last_section_as_evidence():
    """A hung run's trace ends at the section that never finished."""
    w.begin_run()
    w.mark("Signals tab")
    # ...hang: end_run never called; next run reads the evidence first.
    assert w.last_run_completed() is False
    lines = [x for x in w.read_trace().splitlines() if x.strip()]
    assert lines[-1].endswith("Signals tab")


def test_no_trace_returns_none():
    assert w.last_run_completed() is None


def test_arm_and_disarm_write_hang_header_and_never_raise():
    w.arm()
    w.disarm()
    assert "watchdog armed" in w.read_hang_dump()
    w.clear_hang_dump()
    assert w.read_hang_dump() == ""


def test_hang_dump_fires_on_real_stall(tmp_path, monkeypatch):
    """A run exceeding the timeout gets thread stacks dumped."""
    monkeypatch.setattr(w, "HANG_TIMEOUT_S", 0.3)
    import time

    w.arm()
    time.sleep(0.8)  # exceed the timeout -> faulthandler dumps stacks
    w.disarm()
    dump = w.read_hang_dump()
    assert "Thread" in dump or "Stack" in dump or "File" in dump, dump
