"""Run-progress: engine sentinels -> runner state -> snapshot."""

from src.gui.core.engine_proc import PROGRESS_SENTINEL
from src.gui.core.runner import TradeRunner
from src.gui.core.vault import Vault


def _runner(tmp_path) -> TradeRunner:
    return TradeRunner(Vault(tmp_path / "vault.json"))


def test_plan_start_done_fail_flow(tmp_path):
    r = _runner(tmp_path)
    r._apply_progress("PLAN", "fidelity,chase,robinhood")
    assert r.snapshot().progress == (
        ("fidelity", "pending"),
        ("chase", "pending"),
        ("robinhood", "pending"),
    )
    r._apply_progress("START", "fidelity")
    r._apply_progress("DONE", "fidelity")
    r._apply_progress("START", "chase")
    r._apply_progress("FAIL", "chase")
    prog = dict(r.snapshot().progress)
    assert prog == {
        "fidelity": "done",
        "chase": "failed",
        "robinhood": "pending",
    }


def test_start_without_plan_is_tracked(tmp_path):
    r = _runner(tmp_path)
    r._apply_progress("START", "sofi")
    assert r.snapshot().progress == (("sofi", "running"),)


def test_progress_default_empty(tmp_path):
    assert _runner(tmp_path).snapshot().progress == ()


def test_sentinel_is_nul_wrapped():
    # Must be unspoofable by normal broker output.
    assert PROGRESS_SENTINEL.startswith("\x00")
    assert PROGRESS_SENTINEL.endswith("\x00")
