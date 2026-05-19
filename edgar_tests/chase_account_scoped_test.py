"""Chase account-scoped order URL patch (no network)."""

import chase.order as co
import pytest

from src.brokerages import _chase_account_scoped_order as scoped


@pytest.fixture(autouse=True)
def _restore():
    saved_order_page = co.order_page
    saved_place = co.Order.place_order
    saved_applied = scoped._applied
    yield
    co.order_page = saved_order_page
    co.Order.place_order = saved_place
    scoped._applied = saved_applied
    scoped._CURRENT_ACCOUNT_ID.set(None)


def test_generic_when_no_account_context():
    base = co.order_page()
    scoped._applied = False
    scoped.apply()
    # No in-flight place_order -> unchanged generic URL.
    assert co.order_page() == base
    assert ";ai=" not in co.order_page()


def test_place_order_scopes_url_to_account_then_resets():
    seen = {}

    def _spy(self, *a, **k):  # noqa: ANN001, ANN002, ANN003
        seen["url"] = co.order_page()
        return {"ORDER VALIDATION": "ok"}

    co.Order.place_order = _spy
    scoped._applied = False
    scoped.apply()

    result = co.Order.place_order(object(), account_id="98765")
    assert result == {"ORDER VALIDATION": "ok"}
    # During the call the order page was scoped to that account…
    assert seen["url"].endswith(";ai=98765")
    assert "/oi-trade/equity/entry;ai=98765" in seen["url"]
    # …and the context var is reset afterwards (no leak to other calls).
    assert scoped._CURRENT_ACCOUNT_ID.get() is None
    assert ";ai=" not in co.order_page()


def test_positional_account_id_and_no_double_scope():
    seen = {}

    def _spy(self, *a, **k):  # noqa: ANN001, ANN002, ANN003
        seen["url"] = co.order_page()
        return None

    co.Order.place_order = _spy
    scoped._applied = False
    scoped.apply()
    scoped.apply()  # idempotent

    co.Order.place_order(object(), "55555", 1)  # account_id positional
    assert seen["url"].count(";ai=") == 1
    assert seen["url"].endswith(";ai=55555")
