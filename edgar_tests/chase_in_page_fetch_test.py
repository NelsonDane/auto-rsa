"""Chase direct-order in-page fetch transport + tightened success check.

Covers the f8152fb refactor (curl_cffi -> page.evaluate(fetch)) plus
the safety-audit fixes: authoritative session.page, x-jpmc-channel
header, origin guard, and the live-success-requires-order-id check.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from src.brokerages import _chase_direct_order as direct
from src.brokerages.chase_api import _order_succeeded


class _FakePage:
    """Minimal zendriver Tab stand-in: records evaluate() calls and
    returns scripted results. The origin probe and the fetch IIFE
    are distinguished by the expression contents."""

    def __init__(self, *, origin="https://secure.chase.com/web/auth/dashboard",
                 fetch_result=None):
        self.origin = origin
        self.fetch_result = fetch_result
        self.calls: list[str] = []

    async def evaluate(self, expression, await_promise=False, return_by_value=True):  # noqa: ARG002, FBT002
        self.calls.append(expression)
        if "window.location.href" in expression and "fetch(" not in expression:
            return self.origin
        # The fetch IIFE — return whatever the test scripted, as a
        # JSON string (the real JS returns JSON.stringify(...)).
        return self.fetch_result


def _ok(data):
    return json.dumps({"ok": True, "data": data})


def _err(status, body=""):
    return json.dumps({"ok": False, "status": status, "body": body})


# --- _in_page_fetch transport -----------------------------------------

def test_fetch_returns_parsed_data_on_2xx():
    page = _FakePage(fetch_result=_ok({"orderIdentifier": "OID-1"}))
    out = asyncio.run(
        direct._in_page_fetch(page, "https://secure.chase.com/svc/x", label="t", t0=0.0),
    )
    assert out == {"orderIdentifier": "OID-1"}


def test_fetch_returns_none_on_non_2xx():
    page = _FakePage(fetch_result=_err(400, "bad request"))
    out = asyncio.run(
        direct._in_page_fetch(page, "https://secure.chase.com/svc/x", label="t", t0=0.0),
    )
    assert out is None


def test_fetch_aborts_on_wrong_origin():
    """Origin guard: if the tab is on the login subdomain (or any
    non-secure.chase.com origin) the fetch must NOT fire — a
    cross-origin request would carry the wrong cookies / be CORS
    rejected. Must return None without ever evaluating the fetch."""
    page = _FakePage(origin="https://secure05c.chase.com/web/auth/#/logon")
    out = asyncio.run(
        direct._in_page_fetch(page, "https://secure.chase.com/svc/x", label="t", t0=0.0),
    )
    assert out is None
    # Only the origin probe ran; the fetch IIFE never did.
    assert all("fetch(" not in c for c in page.calls)


def test_fetch_none_page_returns_none():
    out = asyncio.run(
        direct._in_page_fetch(None, "https://secure.chase.com/svc/x", label="t", t0=0.0),
    )
    assert out is None


def test_fetch_includes_jpmc_channel_header():
    """The x-jpmc-channel: id=C30 header is required by Chase; its
    omission was a blanket-rejection risk flagged in the audit."""
    page = _FakePage(fetch_result=_ok({"orderIdentifier": "OID-1"}))
    asyncio.run(
        direct._in_page_fetch(
            page, "https://secure.chase.com/svc/x", label="t", t0=0.0,
            method="POST", body={"a": 1},
        ),
    )
    fetch_js = next(c for c in page.calls if "fetch(" in c)
    assert "x-jpmc-channel" in fetch_js
    assert "id=C30" in fetch_js
    # x-requested-with was an unverified deviation from Chase's real
    # headers; it should NOT be sent.
    assert "x-requested-with" not in fetch_js


def test_fetch_post_includes_body():
    page = _FakePage(fetch_result=_ok({"orderIdentifier": "OID-1"}))
    asyncio.run(
        direct._in_page_fetch(
            page, "https://secure.chase.com/svc/x", label="t", t0=0.0,
            method="POST", body={"securitySymbolCode": "TSLA"},
        ),
    )
    fetch_js = next(c for c in page.calls if "fetch(" in c)
    assert "TSLA" in fetch_js
    assert "'POST'" in fetch_js


# --- _order_succeeded (tightened live-success check) ------------------

def test_dry_run_success_on_validation_only():
    msgs = {"ORDER VALIDATION": {"some": "data"}, "ORDER CONFIRMATION": ""}
    assert _order_succeeded(msgs, dry=True) is True


def test_dry_run_fail_without_validation():
    msgs = {"ORDER VALIDATION": "", "ORDER CONFIRMATION": ""}
    assert _order_succeeded(msgs, dry=True) is False


def test_live_success_requires_order_identifier():
    """A live order is EXECUTED only if the confirmation carries an
    order id -- NOT merely because ORDER VALIDATION is truthy. This
    is the audit #5 fix: a 2xx execute with a degenerate body must
    not be scored as a fill."""
    msgs = {
        "ORDER VALIDATION": {"financialInformationExchangeSystemOrderIdentifier": "EX1"},
        "ORDER CONFIRMATION": {"orderIdentifier": "OID-99"},
    }
    assert _order_succeeded(msgs, dry=False) is True


def test_live_fail_on_queue_eligible_only_false_success():
    """The field-confirmed false success: Chase's /buy-orders returned a
    confirmation-shaped body WITH an order id but
    orderQueueAvailabilityIndicator=true for an after-hours order that was
    never actually placed (the IDs didn't appear in any account). It must
    NOT be scored as a fill, even though it carries an order id."""
    msgs = {
        "ORDER VALIDATION": {"financialInformationExchangeSystemOrderIdentifier": "EX1"},
        "ORDER CONFIRMATION": {
            "orderIdentifier": "DA697607",
            "orderQueueAvailabilityIndicator": True,
            "orderDate": "2026-07-17T01:23:26.263Z",
        },
    }
    assert _order_succeeded(msgs, dry=False) is False


def test_live_accepts_2xx_body_without_recognized_id_key():
    """A non-empty 2xx execute body with no recognized order-id key
    (and no reject marker) is now ACCEPTED as a fill. Rationale: the
    execute-response shape isn't confirmed against live Chase, and a
    real fill under an unexpected id key recorded FAILED would cause
    a double-buy on the next run -- the worse failure. Empty bodies
    and explicit rejects still fail (see the tests below)."""
    msgs = {
        "ORDER VALIDATION": {"financialInformationExchangeSystemOrderIdentifier": "EX1"},
        "ORDER CONFIRMATION": {"orderStatusCode": "ACCEPTED"},  # no id key
    }
    assert _order_succeeded(msgs, dry=False) is True


def test_live_fail_when_confirmation_has_explicit_reject():
    """An explicit rejection echoed inside a 2xx execute body fails."""
    for reject_key in ("tradeErrorMessages", "errors", "errorMessages"):
        msgs = {"ORDER CONFIRMATION": {reject_key: ["rejected"]}}
        assert _order_succeeded(msgs, dry=False) is False, reject_key


def test_live_fail_when_confirmation_not_a_dict():
    msgs = {
        "ORDER VALIDATION": {"financialInformationExchangeSystemOrderIdentifier": "EX1"},
        "ORDER CONFIRMATION": "",
    }
    assert _order_succeeded(msgs, dry=False) is False


def test_live_success_accepts_alternate_id_keys():
    for key in ("orderIdentifier", "orderId",
                "financialInformationExchangeSystemOrderIdentifier"):
        msgs = {"ORDER CONFIRMATION": {key: "X"}}
        assert _order_succeeded(msgs, dry=False) is True, key


@pytest.fixture(autouse=True)
def _restore_patch_state():
    """Don't let apply()'s module-level _applied flag leak between
    this file and the (xfailed) chase_direct_order_test module."""
    saved = direct._applied
    yield
    direct._applied = saved
