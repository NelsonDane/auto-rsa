"""Chase direct-order patch: opt-in, idempotent, skips page nav."""

import asyncio

import chase.order as co
import pytest

from src.brokerages import _chase_direct_order as direct


@pytest.fixture(autouse=True)
def _restore(monkeypatch):
    saved_async = co.Order._place_order_async  # noqa: SLF001
    saved_applied = direct._applied
    yield
    co.Order._place_order_async = saved_async  # noqa: SLF001
    direct._applied = saved_applied
    monkeypatch.delenv("RSA_CHASE_DIRECT_ORDER", raising=False)


def test_opt_in_off_by_default(monkeypatch):
    monkeypatch.delenv("RSA_CHASE_DIRECT_ORDER", raising=False)
    direct._applied = False
    sentinel = co.Order._place_order_async  # noqa: SLF001
    direct.apply()
    # Untouched when flag is unset — guarantees behavior parity with
    # today's path unless the operator explicitly turns it on.
    assert co.Order._place_order_async is sentinel  # noqa: SLF001
    assert not direct._applied


def test_opt_in_on_replaces_with_marker(monkeypatch):
    monkeypatch.setenv("RSA_CHASE_DIRECT_ORDER", "1")
    direct._applied = False
    direct.apply()
    new = co.Order._place_order_async  # noqa: SLF001
    assert getattr(new, "_rsa_chase_direct", False)
    # Re-apply is a no-op (idempotent — single wrap).
    direct._applied = False
    direct.apply()
    assert co.Order._place_order_async is new  # noqa: SLF001


def test_direct_path_posts_validate_then_execute_without_page_nav(
    monkeypatch,
):
    monkeypatch.setenv("RSA_CHASE_DIRECT_ORDER", "1")
    direct._applied = False
    direct.apply()

    calls = []

    class _Resp:
        status_code = 200

        def __init__(self, body):
            self._body = body
            self.text = "ok"

        def json(self):
            return self._body

    def _fake_post(url, **kwargs):
        calls.append((url, kwargs))
        if "validations" in url:
            return _Resp(
                {
                    "financialInformationExchangeSystemOrderIdentifier": "EX1",
                    "tradeErrorMessages": [],
                },
            )
        return _Resp({"orderIdentifier": "OID-99"})

    # Patch the curl_cffi requests module the patch imported.
    import curl_cffi.requests as cc

    monkeypatch.setattr(cc, "post", _fake_post)

    class _Cookie:
        def __init__(self, name, value):
            self.name = name
            self.value = value

    class _CookieJar:
        async def get_all(self):
            return [_Cookie("JSESSIONID", "abc"), _Cookie("a", "b")]

    class _Browser:
        cookies = _CookieJar()

    class _Session:
        browser = _Browser()
        # Intentionally NO `page` attribute — direct path must not touch it.

    class _Order:
        session = _Session()

    out = asyncio.run(
        co.Order._place_order_async(  # noqa: SLF001
            _Order(),
            account_id="2467",
            quantity=1,
            price_type="MARKET",
            symbol="ADTX",
            duration="DAY",
            order_type="SELL",
            dry_run=False,
        ),
    )

    # Both endpoints hit; payload identifies the right account+symbol.
    assert len(calls) == 2
    assert "validations" in calls[0][0]
    assert "sell-orders" in calls[1][0]
    val_payload = calls[0][1]["json"]
    assert val_payload["accountIdentifier"] == 2467
    assert val_payload["securitySymbolCode"] == "ADTX"
    assert val_payload["tradeActionName"] == "SELL"
    # Cookies came from the browser jar, not the page.
    assert calls[0][1]["cookies"]["JSESSIONID"] == "abc"
    # Confirmation surfaced from the execute response.
    assert out["ORDER CONFIRMATION"] == {"orderIdentifier": "OID-99"}
    assert out["ORDER INVALID"] == ""


def test_dry_run_stops_after_validation(monkeypatch):
    monkeypatch.setenv("RSA_CHASE_DIRECT_ORDER", "1")
    direct._applied = False
    direct.apply()
    calls = []

    class _Resp:
        status_code = 200
        text = "ok"

        def json(self):
            return {
                "financialInformationExchangeSystemOrderIdentifier": "EX",
                "tradeErrorMessages": [],
            }

    def _fake_post(url, **kwargs):
        calls.append(url)
        return _Resp()

    import curl_cffi.requests as cc

    monkeypatch.setattr(cc, "post", _fake_post)

    class _C:
        def __init__(self, n, v):
            self.name = n
            self.value = v

    class _Jar:
        async def get_all(self):
            return [_C("x", "y")]

    class _B:
        cookies = _Jar()

    class _S:
        browser = _B()

    class _O:
        session = _S()

    out = asyncio.run(
        co.Order._place_order_async(  # noqa: SLF001
            _O(), account_id="2467", quantity=1, price_type="MARKET",
            symbol="ADTX", duration="DAY", order_type="BUY", dry_run=True,
        ),
    )
    # Only the validate call should have happened — no execute on dry run.
    assert len(calls) == 1
    assert "validations" in calls[0]
    assert out["ORDER CONFIRMATION"] == ""
