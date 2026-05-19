"""Chase order HTTP timeout guard (no network)."""

import chase.order as co
import pytest

from src.brokerages import _chase_request_timeout as crt


@pytest.fixture(autouse=True)
def _restore():
    saved_requests = co.requests
    saved_applied = crt._applied
    yield
    co.requests = saved_requests
    crt._applied = saved_applied


class _Spy:
    def __init__(self):
        self.calls = []
        self.marker = "passthrough-ok"

    def post(self, *a, **k):
        self.calls.append(("post", a, k))
        return "POSTED"

    def get(self, *a, **k):
        self.calls.append(("get", a, k))
        return "GOT"


def test_injects_default_timeout_and_passes_through(monkeypatch):
    crt._applied = False
    crt.apply()
    assert isinstance(co.requests, crt._TimeoutRequests)

    spy = _Spy()
    co.requests._real = spy

    co.requests.post("https://x", json={"a": 1})
    co.requests.get("https://y")
    assert spy.calls[0][2]["timeout"] == crt._DEFAULT_TIMEOUT
    assert spy.calls[1][2]["timeout"] == crt._DEFAULT_TIMEOUT
    # Caller-supplied timeout is respected.
    co.requests.post("https://x", timeout=5)
    assert spy.calls[2][2]["timeout"] == 5
    # Unknown attributes proxy straight through to the real module.
    assert co.requests.marker == "passthrough-ok"


def test_idempotent_no_double_wrap():
    crt._applied = False
    crt.apply()
    first = co.requests
    crt.apply()  # _applied guard
    assert co.requests is first
    crt._applied = False
    crt.apply()  # isinstance guard prevents wrapping a wrapper
    assert isinstance(co.requests, crt._TimeoutRequests)
    assert not isinstance(co.requests._real, crt._TimeoutRequests)


def test_env_override(monkeypatch):
    monkeypatch.setenv("RSA_CHASE_HTTP_TIMEOUT", "12")
    assert crt._timeout() == 12
    monkeypatch.setenv("RSA_CHASE_HTTP_TIMEOUT", "bad")
    assert crt._timeout() == crt._DEFAULT_TIMEOUT
