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
    # Fidelity placed an order (fill counted) -> done.
    r._apply_progress("START", "fidelity")
    r._fill_counts["fidelity"] = 1
    r._apply_progress("DONE", "fidelity")
    # Chase blew up -> failed.
    r._apply_progress("START", "chase")
    r._apply_progress("FAIL", "chase")
    prog = dict(r.snapshot().progress)
    assert prog == {
        "fidelity": "done",
        "chase": "failed",
        "robinhood": "pending",
    }


def test_done_with_zero_fills_is_yellow(tmp_path):
    r = _runner(tmp_path)
    r._apply_progress("PLAN", "bbae")
    r._apply_progress("START", "bbae")
    r._apply_progress("DONE", "bbae")  # no fills observed -> yellow
    assert dict(r.snapshot().progress) == {"bbae": "done_no_fill"}


def test_fill_line_increments_only_during_active_broker(tmp_path):
    from src.outcomes import is_fill_line

    r = _runner(tmp_path)
    r._apply_progress("PLAN", "bbae,public")
    r._apply_progress("START", "bbae")
    # Simulate the pump loop: one fill line during bbae.
    assert is_fill_line("BBAE 1: Buy 1 of LCID in xxxxx7743: Success")
    r._fill_counts["bbae"] = r._fill_counts.get("bbae", 0) + 1
    r._apply_progress("DONE", "bbae")
    # Public ran with no fills.
    r._apply_progress("START", "public")
    r._apply_progress("DONE", "public")
    prog = dict(r.snapshot().progress)
    assert prog == {"bbae": "done", "public": "done_no_fill"}


def test_plan_resets_fill_state(tmp_path):
    r = _runner(tmp_path)
    r._apply_progress("PLAN", "fidelity")
    r._apply_progress("START", "fidelity")
    r._fill_counts["fidelity"] = 3
    # New plan should wipe prior fill bookkeeping.
    r._apply_progress("PLAN", "chase")
    assert r._fill_counts == {}
    assert r._current_broker is None


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
