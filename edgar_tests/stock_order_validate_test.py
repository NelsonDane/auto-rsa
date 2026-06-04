"""StockOrder.order_validate — the previously-dead required-field checks."""

from __future__ import annotations

import pytest

from src.helper_api import StockOrder


def _order(action: str, amount: float, stock: str | None = "ACME") -> StockOrder:
    o = StockOrder()
    if action:
        o.set_action(action)  # type: ignore[arg-type]
    o.set_amount(amount)
    if stock:
        o.set_stock(stock)
    o.set_brokers([])  # brokers checked separately; not our concern here
    return o


def test_zero_amount_is_rejected():
    """Regression: the check was `amount is None` but amount defaults to
    0.0 and is never None, so a 0-share order sailed through."""
    o = StockOrder()
    o.set_action("buy")
    o.set_amount(0)
    o.set_stock("ACME")
    from src.brokers import AllBrokersInfo

    o.set_brokers(AllBrokersInfo().get_all())
    with pytest.raises(ValueError, match="positive number"):
        o.order_validate(pre_login=True)


def test_blank_action_is_rejected():
    o = StockOrder()
    o.set_amount(1)
    o.set_stock("ACME")
    from src.brokers import AllBrokersInfo

    o.set_brokers(AllBrokersInfo().get_all())
    with pytest.raises(ValueError, match="Action must be set"):
        o.order_validate(pre_login=True)


def test_valid_order_passes():
    o = StockOrder()
    o.set_action("buy")
    o.set_amount(1)
    o.set_stock("ACME")
    from src.brokers import AllBrokersInfo

    o.set_brokers(AllBrokersInfo().get_all())
    assert o.order_validate(pre_login=True) is None


def test_holdings_skips_action_amount_checks():
    """A holdings request needs neither action nor a positive amount."""
    o = StockOrder()
    o.set_holdings(holdings=True)
    from src.brokers import AllBrokersInfo

    o.set_brokers(AllBrokersInfo().get_all())
    assert o.order_validate(pre_login=True) is None
