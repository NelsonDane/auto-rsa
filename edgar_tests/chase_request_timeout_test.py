"""Chase order timeout guards: HTTP default + bounded order coroutine."""

import asyncio

import chase.order as co
import chase.symbols as cs
import pytest

from src.brokerages import _chase_request_timeout as crt


@pytest.fixture(autouse=True)
def _restore():
    saved_requests = co.requests
    saved_quote_requests = cs.requests
    saved_async = co.Order._place_order_async  # noqa: SLF001
    saved_applied = crt._applied
    yield
    co.requests = saved_requests
    cs.requests = saved_quote_requests
    co.Order._place_order_async = saved_async  # noqa: SLF001
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


def test_injects_default_timeout_and_passes_through():
    crt._applied = False
    crt.apply()
    assert isinstance(co.requests, crt._TimeoutRequests)
    # Also wraps chase.symbols.requests (used by quote + holdings GETs).
    assert isinstance(cs.requests, crt._TimeoutRequests)
    spy = _Spy()
    co.requests._real = spy
    co.requests.post("https://x", json={"a": 1})
    co.requests.get("https://y")
    assert spy.calls[0][2]["timeout"] == crt._DEFAULT_TIMEOUT
    assert spy.calls[1][2]["timeout"] == crt._DEFAULT_TIMEOUT
    co.requests.post("https://x", timeout=5)
    assert spy.calls[2][2]["timeout"] == 5
    assert co.requests.marker == "passthrough-ok"


def test_env_overrides():
    import os

    os.environ["RSA_CHASE_HTTP_TIMEOUT"] = "12"
    os.environ["RSA_CHASE_ORDER_TIMEOUT"] = "33"
    try:
        assert crt._timeout() == 12
        assert crt._order_timeout() == 33
        os.environ["RSA_CHASE_HTTP_TIMEOUT"] = "bad"
        os.environ["RSA_CHASE_ORDER_TIMEOUT"] = "bad"
        assert crt._timeout() == crt._DEFAULT_TIMEOUT
        assert crt._order_timeout() == crt._DEFAULT_ORDER_TIMEOUT
    finally:
        os.environ.pop("RSA_CHASE_HTTP_TIMEOUT", None)
        os.environ.pop("RSA_CHASE_ORDER_TIMEOUT", None)


def test_order_coroutine_bounded_and_fast_original_passes(monkeypatch):
    monkeypatch.setenv("RSA_CHASE_ORDER_TIMEOUT", "30")

    async def _fast(self, *a, **k):  # noqa: ANN001, ANN002, ANN003
        return {"ORDER CONFIRMATION": "ok"}

    co.Order._place_order_async = _fast  # noqa: SLF001
    crt._applied = False
    crt.apply()
    # Marker set; not double-wrapped on re-apply.
    assert getattr(co.Order._place_order_async, "_rsa_order_bounded", False)  # noqa: SLF001
    crt._applied = False
    crt.apply()
    inner = co.Order._place_order_async.__closure__  # still single wrap  # noqa: SLF001
    assert inner is not None

    out = asyncio.run(co.Order._place_order_async(object()))  # noqa: SLF001
    assert out == {"ORDER CONFIRMATION": "ok"}


def test_order_coroutine_times_out(monkeypatch):
    monkeypatch.setenv("RSA_CHASE_ORDER_TIMEOUT", "30")

    async def _hang(self, *a, **k):  # noqa: ANN001, ANN002, ANN003
        await asyncio.sleep(60)

    co.Order._place_order_async = _hang  # noqa: SLF001
    crt._applied = False
    crt.apply()

    async def _drive():
        # Patch the cap tiny for the test without real waiting.
        monkeypatch.setattr(crt, "_order_timeout", lambda: 0.05)
        with pytest.raises(asyncio.TimeoutError):
            await co.Order._place_order_async(object())  # noqa: SLF001

    asyncio.run(_drive())
