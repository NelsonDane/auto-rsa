"""AllBrokersInfo.parse_input — input normalization + selector membership."""

from __future__ import annotations

from src.brokers import AllBrokersInfo, BrokerName


def test_parse_input_handles_spaces_and_underscores():
    """Regression: "wells fargo" / "wells_fargo" used to return None and
    silently drop the broker from a run."""
    bi = AllBrokersInfo()
    for text in ("wellsfargo", "wells fargo", "wells_fargo", "Wells-Fargo", "WF"):
        broker = bi.parse_input(text)
        assert broker is not None, text
        assert broker.name == BrokerName.WELLS_FARGO, text


def test_parse_input_unknown_returns_none():
    assert AllBrokersInfo().parse_input("definitely-not-a-broker") is None
    assert AllBrokersInfo().parse_input("") is None


def test_parse_input_canonical_and_nicknames():
    bi = AllBrokersInfo()
    assert bi.parse_input("fidelity").name == BrokerName.FIDELITY
    assert bi.parse_input("bb").name == BrokerName.BBAE  # nickname
    assert bi.parse_input("WB").name == BrokerName.WEBULL  # nickname, cased


def test_broker_selector_memberships_are_stable():
    """Pin the selector sets so a regression that adds/drops a broker
    from a real-money selection list fails loudly."""
    bi = AllBrokersInfo()
    assert len(bi.get_all()) == len(list(BrokerName))
    # get_most == everything except Vanguard.
    most = {b.name for b in bi.get_most()}
    assert BrokerName.VANGUARD not in most
    assert most == set(BrokerName) - {BrokerName.VANGUARD}
    # day1 / fast are subsets of all.
    assert {b.name for b in bi.get_day_one()} <= set(BrokerName)
    assert {b.name for b in bi.get_fast()} <= set(BrokerName)
