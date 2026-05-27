"""Tier table + cap rule boundaries."""

from src.license import tiers


def test_tier_caps_are_intentional():
    # Locking in the design doc's numbers so a future "looser" PR
    # has to update the test deliberately.
    assert tiers.TIER_CAPS["unlicensed"] == 1
    assert tiers.TIER_CAPS["basic"] == 1
    assert tiers.TIER_CAPS["advanced"] == 5
    assert tiers.TIER_CAPS["operator"] is None


def test_every_tier_has_a_human_label():
    for tier in tiers.TIER_CAPS:
        assert tiers.TIER_LABEL[tier]
