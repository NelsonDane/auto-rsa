"""Friend-tier per-broker account cap in reserve_or_skip.

'1 account per broker' means: for each broker, only the first account
places an order per run; extra accounts are skipped. Enforced at the
one choke point every broker uses (reserve_or_skip).
"""

import types

import pytest

from src import helper_api, ledger
from src.helper_api import reserve_or_skip, reset_subaccount_caps


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "_DB_PATH", tmp_path / "ledger.db")
    monkeypatch.setattr(helper_api, "account_allowed", lambda *a, **k: True)
    reset_subaccount_caps()
    yield
    reset_subaccount_caps()


def _order(*, dry=True, amount=1.0, action="buy"):
    return types.SimpleNamespace(
        get_action=lambda: action,
        get_dry=lambda: dry,
        get_amount=lambda: amount,
    )


def _set_cap(monkeypatch, value):
    monkeypatch.setattr("src.license.subaccount_cap", lambda: value)


def _reserve(broker, account, order):
    return reserve_or_skip(
        broker_key=broker, account=account, ticker="FOMO", order_obj=order,
    )


def test_cap_one_allows_only_first_account(monkeypatch):
    _set_cap(monkeypatch, 1)
    o = _order()
    assert _reserve("robinhood", "111", o) is not None
    assert _reserve("robinhood", "222", o) is None  # 2nd account blocked
    assert _reserve("robinhood", "333", o) is None


def test_cap_is_per_broker(monkeypatch):
    _set_cap(monkeypatch, 1)
    o = _order()
    assert _reserve("robinhood", "111", o) is not None
    assert _reserve("public", "222", o) is not None      # different broker: ok
    assert _reserve("robinhood", "333", o) is None        # robinhood already used


def test_reset_frees_slots(monkeypatch):
    _set_cap(monkeypatch, 1)
    o = _order()
    assert _reserve("robinhood", "111", o) is not None
    assert _reserve("robinhood", "222", o) is None
    reset_subaccount_caps()  # next run
    assert _reserve("robinhood", "222", o) is not None


def test_no_cap_allows_all(monkeypatch):
    _set_cap(monkeypatch, None)  # pro tiers: unlimited
    o = _order()
    for acct in ("111", "222", "333"):
        assert _reserve("robinhood", acct, o) is not None


def test_friend_tiers_cap_at_one_pro_uncapped():
    from src.license.tiers import SUBACCOUNT_CAPS

    assert SUBACCOUNT_CAPS["friend_lite"] == 1
    assert SUBACCOUNT_CAPS["friend_main"] == 1
    assert SUBACCOUNT_CAPS["operator"] is None
    assert SUBACCOUNT_CAPS["advanced"] is None
    # Pro "try it" state stays uncapped (no per-account cap surprise).
    assert SUBACCOUNT_CAPS["unlicensed"] is None


def test_unlicensed_capped_only_in_friend_build(monkeypatch):
    """The lapsed-friend hole is closed in a friend build, without changing
    pro behavior: manager.subaccount_cap() tightens unlicensed to 1 only
    when REQUIRE_LICENSE_TO_TRADE is set."""
    from src.license import _keys, manager

    monkeypatch.setattr(manager, "current_tier", lambda: "unlicensed")
    monkeypatch.setattr(_keys, "REQUIRE_LICENSE_TO_TRADE", False, raising=False)
    assert manager.subaccount_cap() is None  # pro: unchanged
    monkeypatch.setattr(_keys, "REQUIRE_LICENSE_TO_TRADE", True, raising=False)
    assert manager.subaccount_cap() == 1  # friend build: capped


def test_dedup_skip_releases_the_slot(monkeypatch):
    """A ledger dedup skip did NOT trade, so it must not consume the cap —
    a different account can still take the one slot."""
    _set_cap(monkeypatch, 1)
    monkeypatch.setenv("RSA_PLAY_KEY", "SIG:1")
    # Pre-seed account 111 as already INTENDED -> reserve will dedup-skip it.
    ledger.record_intent(ledger.Play("SIG:1", "robinhood", "111", "FOMO", "buy"), 1.0)
    o = _order(dry=False)
    assert _reserve("robinhood", "111", o) is None       # dedup skip, slot released
    assert _reserve("robinhood", "222", o) is not None    # slot still available
