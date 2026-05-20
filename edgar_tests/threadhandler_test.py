"""ThreadHandler watchdog: daemon, join timeout, is_alive, results."""

import time

from src.helper_api import ThreadHandler


def test_fast_func_completes_and_returns():
    th = ThreadHandler(lambda x: x + 1, 41)
    th.start()
    th.join(timeout=5)
    assert th.is_alive() is False
    assert th.get_result() == (42, None)


def test_exception_is_captured():
    def boom() -> None:
        msg = "kaboom"
        raise RuntimeError(msg)

    th = ThreadHandler(boom)
    th.start()
    th.join(timeout=5)
    assert th.is_alive() is False
    result, err = th.get_result()
    assert result is None
    assert "kaboom" in err


def test_hung_func_times_out_and_is_daemon():
    th = ThreadHandler(time.sleep, 30)  # would block the run forever
    # Daemon so a wedged broker can't keep the process/scheduler alive.
    assert th.thread.daemon is True
    th.start()
    th.join(timeout=0.2)
    # Watchdog: still running after the bounded join -> caller abandons.
    assert th.is_alive() is True
