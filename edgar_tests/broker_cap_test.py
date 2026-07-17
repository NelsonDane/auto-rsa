"""SEC-2: engine-level parent-broker cap (friend build only)."""

import types

from src.helper_api import broker_cap_message


class _BI:
    def __init__(self, name):
        self.name = name


def _order(brokers, *, notbrokers=(), holdings=False):
    return types.SimpleNamespace(
        get_holdings=lambda: holdings,
        get_brokers=lambda: [_BI(b) for b in brokers],
        get_notbrokers=lambda: list(notbrokers),
    )


def _friend(monkeypatch, cap):
    from src.license import _keys

    monkeypatch.setattr(_keys, "REQUIRE_LICENSE_TO_TRADE", True, raising=False)
    monkeypatch.setattr("src.license.account_cap", lambda: cap)


def test_over_cap_run_is_blocked_in_friend_build(monkeypatch):
    _friend(monkeypatch, 1)
    msg = broker_cap_message(_order(["chase", "robinhood"]))
    assert "permits 1 broker" in msg
    assert "No orders were placed" in msg


def test_at_cap_is_allowed(monkeypatch):
    _friend(monkeypatch, 1)
    assert broker_cap_message(_order(["chase"])) == ""


def test_multiple_subaccounts_count_as_one_broker(monkeypatch):
    _friend(monkeypatch, 1)
    # Same broker repeated (e.g. Chase's 8 sub-accounts) = 1 parent broker.
    assert broker_cap_message(_order(["chase", "chase", "chase"])) == ""


def test_holdings_run_is_exempt(monkeypatch):
    _friend(monkeypatch, 1)
    assert broker_cap_message(_order(["chase", "robinhood"], holdings=True)) == ""


def test_cap_none_allows_all(monkeypatch):
    _friend(monkeypatch, None)  # friend_main / bypass / operator
    assert broker_cap_message(_order(["a", "b", "c"])) == ""


def test_pro_build_is_noop(monkeypatch):
    from src.license import _keys

    monkeypatch.setattr(_keys, "REQUIRE_LICENSE_TO_TRADE", False, raising=False)
    monkeypatch.setattr("src.license.account_cap", lambda: 1)
    # Pro build keeps the vault-only cap; the engine does not enforce it.
    assert broker_cap_message(_order(["chase", "robinhood", "fennel"])) == ""
