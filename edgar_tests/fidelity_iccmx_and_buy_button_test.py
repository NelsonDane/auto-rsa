"""Fidelity ICCM->ICCMX typeahead + 30s buy-menu hang fixes (live-bug patches)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def patched_transaction():
    """Build a fake FidelityAutomation, apply our patch, return the
    swapped-in transaction method bound to the fake instance."""
    fake_fidelity_mod = MagicMock()

    class FakeAutomation:
        page = MagicMock()

        def wait_for_loading_sign(self) -> None:
            pass

    fake_fidelity_mod.FidelityAutomation = FakeAutomation

    fake_pw_sync = MagicMock()
    fake_pw_sync.TimeoutError = RuntimeError  # use a real exception class

    with patch.dict("sys.modules", {
        "fidelity": MagicMock(fidelity=fake_fidelity_mod),
        "fidelity.fidelity": fake_fidelity_mod,
        "playwright.sync_api": fake_pw_sync,
    }):
        from src.brokerages import _fidelity_iccmx_and_buy_button as patch_mod

        # Force re-apply for test isolation.
        patch_mod._applied = False
        patch_mod.apply()

    return FakeAutomation


def test_apply_is_idempotent():
    """Calling apply() multiple times shouldn't wrap repeatedly."""
    from src.brokerages import _fidelity_iccmx_and_buy_button as patch_mod

    patch_mod._applied = True
    # Should be a no-op; not raise.
    patch_mod.apply()
    assert patch_mod._applied is True


def test_apply_tolerates_missing_upstream_package(monkeypatch, capsys):
    """If `fidelity` isn't installed in the venv, apply() logs and
    no-ops — the rest of src.brokerages must still import."""
    from src.brokerages import _fidelity_iccmx_and_buy_button as patch_mod

    patch_mod._applied = False

    import builtins
    real_import = builtins.__import__

    def _block_fidelity(name, *args, **kwargs):
        if name == "fidelity" or name.startswith("fidelity."):
            msg = "no module"
            raise ImportError(msg)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_fidelity)
    patch_mod.apply()
    assert patch_mod._applied is False
    captured = capsys.readouterr()
    assert "not applied" in captured.out


def test_symbol_field_clicks_exact_match_when_dropdown_offers_one(patched_transaction):
    """The Issue-1 fix: when the typeahead dropdown contains an
    option starting with the typed ticker followed by a word
    boundary (i.e. an EXACT symbol match like 'ICCM CompanyName'
    vs the auto-resolution 'ICCMX FundName'), click that option
    rather than pressing Enter. Pressing Enter selects the
    highlighted option, which is what got us ICCMX previously."""
    inst = patched_transaction()
    page = inst.page
    page.get_by_label.return_value.input_value.return_value = "ICCM"
    page.get_by_role.return_value.is_visible.return_value = True
    # Quote panel text must contain the typed ticker as a whole word.
    page.locator.return_value.inner_text.return_value = "ICCM IceCure Medical $1.34"

    inst.transaction(
        stock="ICCM", quantity=1, action="buy",
        account="Z12345", dry=True,
    )
    # Exact-match option should have been clicked at least once.
    option_clicks = page.get_by_role.return_value.filter.return_value.first.click.call_args_list
    assert len(option_clicks) >= 1, (
        "Exact-match dropdown option should be clicked when offered"
    )


def test_symbol_field_falls_back_to_escape_enter_when_no_exact_match(patched_transaction):
    """When the typeahead doesn't expose an exact symbol match
    (option.is_visible returns False), we should NOT press Enter
    on a potentially-highlighted wrong suggestion. Instead, press
    Escape to dismiss the dropdown and press Enter on the input
    so the literal text is submitted -- then the input_value /
    quote panel checks below catch any backend substitution."""
    inst = patched_transaction()
    page = inst.page
    page.get_by_label.return_value.input_value.return_value = "ICCM"
    page.get_by_role.return_value.is_visible.return_value = True
    page.locator.return_value.inner_text.return_value = "ICCM IceCure Medical $1.34"

    # Make the exact-match option NOT visible -> fall back path.
    page.get_by_role.return_value.filter.return_value.first.is_visible.return_value = False

    inst.transaction(
        stock="ICCM", quantity=1, action="buy",
        account="Z12345", dry=True,
    )
    escape_calls = [
        c for c in page.keyboard.press.call_args_list
        if c.args and c.args[0] == "Escape"
    ]
    assert len(escape_calls) >= 1, (
        "Fallback path must press Escape when no exact match offered"
    )


def test_symbol_mismatch_guard_aborts_with_clear_message(patched_transaction):
    """Defense-in-depth: if Escape didn't dismiss the typeahead for
    some reason and Fidelity ends up with ICCMX in the Symbol field,
    return False with a clear message instead of buying the wrong
    ticker. Checks input_value() (not the quote panel text), since
    ICCM is a substring of ICCMX and substring checks aren't safe."""
    inst = patched_transaction()
    page = inst.page
    # Symbol input shows the autocomplete's pick, not our literal text.
    page.get_by_label.return_value.input_value.return_value = "ICCMX"

    ok, msg = inst.transaction(
        stock="ICCM", quantity=1, action="buy",
        account="Z12345", dry=True,
    )
    assert ok is False
    assert "Symbol mismatch" in msg
    assert "ICCM" in msg
    assert "ICCMX" in msg


def test_action_menu_retry_uses_fast_timeout(patched_transaction):
    """Issue 2 fix: when the action dropdown is being clicked, the
    timeout kwarg should be 3000 (3s), not omitted (which would use
    Playwright's default 30s). This is the change that prevents the
    150-second hang we saw on live ICCM."""
    inst = patched_transaction()
    page = inst.page
    # Pass the symbol-mismatch guard.
    page.get_by_label.return_value.input_value.return_value = "ICCM"

    # Force the target_option to be NOT visible initially so the
    # patched code path that calls action_dropdown.click(timeout=3000)
    # actually fires.
    target_option = MagicMock()
    target_option.is_visible.return_value = False
    target_option.click.return_value = None  # success on first try
    page.get_by_role.side_effect = lambda *a, **k: target_option

    inst.transaction(
        stock="ICCM", quantity=1, action="buy",
        account="Z12345", dry=True,
    )
    timeout_clicks = [
        c for c in page.locator.return_value.click.call_args_list
        if c.kwargs.get("timeout") == 3000  # noqa: PLR2004
    ]
    assert len(timeout_clicks) >= 1, (
        "action_dropdown.click should carry timeout=3000 so attempts "
        "fail fast instead of hanging 30s each"
    )
