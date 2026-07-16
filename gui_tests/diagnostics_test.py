"""Tests for the GUI diagnostics / troubleshooting helpers."""

from __future__ import annotations

import json
import os
import time

from src.gui.core import diagnostics as d


def test_quick_checks_report_vault_states():
    checks = d.quick_health_checks(vault_initialized=False, vault_unlocked=False)
    names = {c.name: c for c in checks}
    assert names["Vault"].status == d.WARN
    assert "no vault" in names["Vault"].detail
    # Every check has a valid status + an icon.
    for c in checks:
        assert c.status in {d.OK, d.WARN, d.FAIL}
        assert c.icon in {"🟢", "🟡", "🔴"}

    ok = {c.name: c for c in d.quick_health_checks(
        vault_initialized=True, vault_unlocked=True)}
    assert ok["Vault"].status == d.OK


def test_run_lock_inspection_and_staleness(tmp_path, monkeypatch):
    lock = tmp_path / "run.lock"
    monkeypatch.setattr(d, "_RUN_LOCK", lock)

    assert d.inspect_run_lock() is None  # no lock

    # A lock owned by THIS live process -> not stale.
    lock.write_text(json.dumps(
        {"engine_pid": None, "owner_pid": os.getpid(), "created": time.time()}))
    info = d.inspect_run_lock()
    assert info is not None
    assert info["stale"] is False
    assert info["owner_alive"] is True

    # A lock owned by a dead pid with a dead engine -> stale.
    lock.write_text(json.dumps(
        {"engine_pid": 999_999_999, "owner_pid": 999_999_998, "created": time.time()}))
    info = d.inspect_run_lock()
    assert info["stale"] is True


def test_force_release_run_lock(tmp_path, monkeypatch):
    lock = tmp_path / "run.lock"
    monkeypatch.setattr(d, "_RUN_LOCK", lock)
    assert d.force_release_run_lock() is False  # nothing to remove
    lock.write_text("{}")
    assert d.force_release_run_lock() is True
    assert not lock.exists()


def test_run_lock_health_row_flags_stale(tmp_path, monkeypatch):
    lock = tmp_path / "run.lock"
    monkeypatch.setattr(d, "_RUN_LOCK", lock)
    lock.write_text(json.dumps(
        {"engine_pid": 999_999_999, "owner_pid": 999_999_998, "created": time.time()}))
    row = d._check_run_lock()
    assert row.status == d.FAIL
    assert "blocks every new run" in row.detail


def test_list_and_read_run_logs(tmp_path, monkeypatch):
    logs_dir = tmp_path / "run_logs"
    logs_dir.mkdir()
    monkeypatch.setattr(d, "_RUN_LOGS", logs_dir)
    (logs_dir / "20260710T204312Z_error.log").write_text("line1\nboom traceback\n")
    (logs_dir / "20260710T204500Z_finished.log").write_text("all good\n")

    logs = d.list_run_logs()
    assert len(logs) == 2
    # Newest first (204500 > 204312).
    assert logs[0]["status"] == "finished"
    assert logs[1]["status"] == "error"
    assert logs[0]["when"] is not None

    content = d.read_run_log(logs[1]["path"])
    assert "boom traceback" in content
    # Tail trims.
    tailed = d.read_run_log(logs[1]["path"], tail=1)
    assert "line1" not in tailed
    assert "boom traceback" in tailed


def test_read_run_log_missing_is_graceful():
    out = d.read_run_log("/nonexistent/path/x.log")
    assert "could not read" in out


def test_engine_import_check_returns_a_row():
    # Runs the real subprocess import; in this repo the result depends on
    # installed deps, so just assert it returns a well-formed row fast-ish.
    row = d.check_engine_importable(timeout=90)
    assert row.name == "Engine import"
    assert row.status in {d.OK, d.WARN, d.FAIL}
