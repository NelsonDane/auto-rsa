"""Orchestration of the parallel broker driver (run_broker is mocked)."""

from __future__ import annotations

import threading
import time

import pytest

from src import auto_rsa_parallel as par


class _FakeName(str):
    """Behaves like a broker name: str()/.lower() give the key."""


class _BrokerInfo:
    def __init__(self, key: str):
        self.name = _FakeName(key.upper())  # fun_run uses .name.lower()


class _Order:
    def __init__(self, brokers, *, holdings=False, notbrokers=()):
        self._brokers = [_BrokerInfo(b) for b in brokers]
        # notbrokers must reference the SAME objects (real code compares
        # BrokerName enum singletons via `in`).
        by_key = {par._broker_key(bi): bi for bi in self._brokers}
        self._not = [by_key[k] for k in notbrokers if k in by_key]
        self._holdings = holdings
        self.validated = 0

    def get_brokers(self):
        return self._brokers

    def get_notbrokers(self):
        return self._not

    def get_holdings(self):
        return self._holdings

    def order_validate(self, *, pre_login=False):
        self.validated += 1


class _FakeAuto:
    def __init__(self, timeout=30.0):
        self.progress = []
        self.messages = []
        self._timeout = timeout
        self._lock = threading.Lock()

    def _emit_progress(self, kind, value):
        with self._lock:
            self.progress.append((kind, value))

    def print_and_discord(self, msg, loop=None):  # noqa: ARG002
        self.messages.append(msg)

    def _broker_timeout(self):
        return self._timeout


@pytest.fixture
def fake_auto(monkeypatch):
    fa = _FakeAuto()
    monkeypatch.setattr(par, "_auto", lambda: fa)
    return fa


def test_browser_sequential_then_api_concurrent(fake_auto, monkeypatch):
    calls = []
    lock = threading.Lock()

    def _rb(bi, order, bot=None, loop=None, *, docker_mode=False):
        with lock:
            calls.append(par._broker_key(bi))
        return (False, 100.0)

    monkeypatch.setattr(par, "run_broker", _rb)
    order = _Order(["bbae", "fidelity", "dspac", "wellsfargo"])
    par.fun_run_parallel(order, cap=4)

    # Every broker ran, order validated exactly once.
    assert set(calls) == {"bbae", "fidelity", "dspac", "wellsfargo"}
    assert order.validated == 1
    # Browser brokers (sequential) run before any API broker.
    assert calls[0] in {"fidelity", "wellsfargo"}
    assert calls[1] in {"fidelity", "wellsfargo"}
    # PLAN lists all brokers.
    assert ("PLAN", "bbae,fidelity,dspac,wellsfargo") in fake_auto.progress


def test_each_broker_gets_its_own_order_copy(fake_auto, monkeypatch):
    # CRITICAL race fix: concurrent brokers must NOT share one StockOrder
    # (firstrade/webull rewrite amount/action mid-order). Every broker must
    # receive a distinct copy, and never the caller's original object.
    orders = []
    lock = threading.Lock()

    def _rb(bi, order, *a, **k):
        with lock:
            orders.append(id(order))
        return (False, 0.0)

    monkeypatch.setattr(par, "run_broker", _rb)
    order = _Order(["bbae", "dspac", "fidelity"])
    par.fun_run_parallel(order, cap=3)
    assert len(set(orders)) == 3  # all distinct
    assert id(order) not in orders  # never the shared original


def test_totals_summed_for_holdings(fake_auto, monkeypatch):
    monkeypatch.setattr(par, "run_broker", lambda bi, o, *a, **k: (False, 50.0))
    order = _Order(["bbae", "dspac", "public"], holdings=True)
    par.fun_run_parallel(order)
    assert any("Combined Total Value" in m and "150.00" in m for m in fake_auto.messages)


def test_cap_limits_concurrency(fake_auto, monkeypatch):
    active = {"now": 0, "max": 0}
    lock = threading.Lock()

    def _rb(bi, order, *a, **k):
        with lock:
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
        time.sleep(0.05)
        with lock:
            active["now"] -= 1
        return (False, 0.0)

    monkeypatch.setattr(par, "run_broker", _rb)
    order = _Order(["bbae", "dspac", "public", "robinhood", "schwab"])
    par.fun_run_parallel(order, cap=2)
    assert active["max"] <= 2  # never more than the cap concurrently


def test_notbrokers_excluded(fake_auto, monkeypatch):
    seen = []
    monkeypatch.setattr(
        par, "run_broker",
        lambda bi, o, *a, **k: (seen.append(par._broker_key(bi)), (False, 0.0))[1],
    )
    order = _Order(["bbae", "dspac"], notbrokers=["dspac"])
    par.fun_run_parallel(order)
    assert seen == ["bbae"]


def test_hung_api_broker_marked_failed(fake_auto, monkeypatch):
    monkeypatch.setattr(par, "_JOIN_GRACE_SECONDS", 0.2)
    fake_auto._timeout = 0.1
    release = threading.Event()

    def _rb(bi, order, *a, **k):
        if par._broker_key(bi) == "bbae":
            release.wait(timeout=5)  # simulate a hang until released
        return (False, 0.0)

    monkeypatch.setattr(par, "run_broker", _rb)
    order = _Order(["bbae", "dspac"])
    try:
        par.fun_run_parallel(order, cap=2)
        # The hung broker is reported FAIL and the run still completes.
        assert ("FAIL", "bbae") in fake_auto.progress
        assert any("complete in all brokers" in m for m in fake_auto.messages)
    finally:
        release.set()


def test_validation_failure_aborts_and_fails_all(fake_auto, monkeypatch):
    monkeypatch.setattr(par, "run_broker", lambda *a, **k: (False, 0.0))

    def _boom(*, pre_login=False):
        raise ValueError("bad order")

    order = _Order(["bbae", "dspac"])
    order.order_validate = _boom
    par.fun_run_parallel(order)
    fails = [p for p in fake_auto.progress if p[0] == "FAIL"]
    assert {v for _k, v in fails} == {"bbae", "dspac"}
