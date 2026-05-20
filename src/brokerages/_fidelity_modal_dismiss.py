"""Stop one rejected Fidelity order from cascading into the next account.

When ``FidelityAutomation.transaction`` submits an order Fidelity
refuses (e.g. error **030910** — a *market* order placed outside
market hours), Fidelity renders a blocking overlay
``<pvd-ett-modal class="eq-ticket-error-modal-component">``. Upstream
only knows how to close the *older* error dialog (it clicks a button
named "Close dialog"), so this newer modal is left on screen. The
auto-rsa account loop reloads the page only once per *stock*, not per
*account* (``fidelity_api.fidelity_transaction``), and upstream
``transaction`` skips its own reload while the URL is still the order
-entry page — so the overlay intercepts every subsequent account's
clicks and each one times out for 30s with an empty/garbled error.

This wraps ``transaction`` to:

* before each call, defensively clear any leftover error modal so the
  account starts on a clean ticket;
* after each call, if the modal is present, harvest its real text
  (so the genuine reason, e.g. 030910, reaches the results table
  instead of "Could not retrieve error message from popup") and
  dismiss it.

Best-effort, idempotent and reversible: every step is wrapped so it
can only ever *improve* on the cascade, never make a run worse. If the
upstream shape changes the patch simply no-ops.
"""

from __future__ import annotations

import contextlib

_applied = False

# The blocking overlay Fidelity shows for a rejected order. The host is
# a custom element whose box is zero-sized, so Playwright's is_visible()
# reports False even while its overlay subtree intercepts every click --
# presence/dismissal must key off the element + its pvd-open attribute,
# never is_visible().
_MODAL = "pvd-ett-modal.eq-ticket-error-modal-component"
_MODAL_OPEN = 'pvd-ett-modal.eq-ticket-error-modal-component[pvd-open="true"]'
# Generic upstream failure strings worth replacing with the modal's
# real text when we can read it.
_GENERIC = (
    "could not retrieve error message",
    "order preview is not what is expected",
    "driver timed out",
    "some error occurred",
)


def _modal_open(page: object) -> bool:
    """Report whether the error modal is present and open (not is_visible-based)."""
    try:
        return page.locator(_MODAL_OPEN).count() > 0  # type: ignore[attr-defined]
    except Exception:
        return False


def _wait_gone(page: object) -> bool:
    """Poll up to ~2s for the open modal to clear; True once it has."""
    for _ in range(20):
        if not _modal_open(page):
            return True
        with contextlib.suppress(Exception):
            page.wait_for_timeout(100)  # type: ignore[attr-defined]
    return not _modal_open(page)


def _modal_text(page: object) -> str:
    """Return the error text of the modal, or "" if absent."""
    if not _modal_open(page):
        return ""
    try:
        # text_content (not inner_text) -- works on the zero-box host.
        raw = page.locator(_MODAL).first.text_content(timeout=2000) or ""  # type: ignore[attr-defined]
    except Exception:
        return ""
    # Collapse the whitespace Fidelity pads error bodies with.
    return " ".join(raw.split()).strip()


def _dismiss_modal(page: object) -> None:
    """Best-effort close of the error modal so the next account is clean."""
    if not _modal_open(page):
        return
    # 1) The accessible close control (pvd-close-button-a11y-text="Close dialog").
    with contextlib.suppress(Exception):
        page.get_by_role("button", name="Close dialog").first.click(timeout=2000)  # type: ignore[attr-defined]
        if _wait_gone(page):
            return
    # 2) Any button inside the modal (Edit order / OK / Got it).
    with contextlib.suppress(Exception):
        btns = page.locator(f"{_MODAL} button")  # type: ignore[attr-defined]
        if btns.count() > 0:
            btns.first.click(timeout=2000)
            if _wait_gone(page):
                return
    # 3) Escape key.
    with contextlib.suppress(Exception):
        page.keyboard.press("Escape")  # type: ignore[attr-defined]
        if _wait_gone(page):
            return
    # 4) Last resort: hard-reload the order-entry page.
    with contextlib.suppress(Exception):
        page.goto("https://digital.fidelity.com/ftgw/digital/trade-equity/index/orderEntry")  # type: ignore[attr-defined]


def apply() -> None:
    """Wrap FidelityAutomation.transaction with modal cleanup. Idempotent."""
    global _applied  # noqa: PLW0603
    if _applied:
        return
    try:
        from fidelity import fidelity as _f  # noqa: PLC0415

        original = _f.FidelityAutomation.transaction

        def _transaction_with_cleanup(
            self: object,
            *args: object,
            **kwargs: object,
        ) -> tuple[bool, str | None]:
            page = getattr(self, "page", None)
            # Clear any leftover modal from a prior rejected account.
            if page is not None:
                _dismiss_modal(page)

            success, error_message = original(self, *args, **kwargs)  # type: ignore[misc]

            if page is not None:
                modal = _modal_text(page)
                if not success and modal:
                    msg = (error_message or "").strip()
                    if not msg or any(g in msg.lower() for g in _GENERIC):
                        error_message = modal
                # Always dismiss so the next account starts clean.
                _dismiss_modal(page)
            return success, error_message

        _f.FidelityAutomation.transaction = _transaction_with_cleanup  # type: ignore[invalid-assignment]
        _applied = True
        print("Fidelity: error-modal cascade guard active")
    except Exception as exc:
        print(f"Fidelity: modal-dismiss patch not applied ({exc})")
