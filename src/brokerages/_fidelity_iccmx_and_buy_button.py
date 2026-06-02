"""Fix two real-money Fidelity issues observed on a live ICCM buy run.

Issue 1 — Symbol typeahead substitutes the first autocomplete hit
------------------------------------------------------------------
Upstream ``FidelityAutomation.transaction`` at lines 829-833 fills
the Symbol input then presses Enter. Fidelity's typeahead has
typically already selected the FIRST suggestion by the time Enter
fires, so a literal ticker like ``ICCM`` gets submitted as
``ICCMX`` (the autocomplete's nearest match — a mutual fund whose
name starts with the same prefix). The quote panel then loads the
WRONG security and every account's order is for the wrong ticker.

Fix: after ``fill(stock)``, press Escape to dismiss the typeahead
dropdown BEFORE pressing Enter. The literal value in the input
field stays — Enter submits exactly what was typed.

Issue 2 — Action menu (Buy/Sell) retry loop hangs 30s per attempt
-----------------------------------------------------------------
Upstream lines 890-913 retry the action-dropdown click 5 times.
The retry's ``action_dropdown.click(force=True)`` call has no
explicit timeout, so it uses Playwright's default 30s. Result: an
account whose page state is wrong burns 5 x 30s = 150 seconds
before the loop gives up — and during that time the run is
completely frozen with no progress.

Fix: set an explicit 3s timeout on the inner click. Combined with
the existing ``target_option.click(timeout=3000)``, each retry
fails fast in ~3s instead of ~30s.

Implementation: full ``transaction()`` method replacement. Tagged
with ``# PATCH:`` comments at the two lines that diverge from
upstream. Verbose but surgical — anyone diffing this against
``fidelity/fidelity.py:transaction`` can see exactly what changed.
"""

from __future__ import annotations

import contextlib

_applied = False


def apply() -> None:  # noqa: C901, PLR0915
    """Replace FidelityAutomation.transaction with the fixed version.

    Idempotent; tolerant of upstream import failure (logs and
    no-ops so a venv without the package still imports the rest
    of src.brokerages cleanly).
    """
    global _applied  # noqa: PLW0603
    if _applied:
        return
    try:
        from fidelity import fidelity as _f  # noqa: PLC0415
        from playwright.sync_api import (  # noqa: PLC0415
            TimeoutError as PlaywrightTimeoutError,
        )
    except Exception as exc:
        print(f"Fidelity: ICCMX+buy-button patch not applied ({exc})")
        return

    def transaction(  # noqa: C901, PLR0911, PLR0912, PLR0914, PLR0915, PLR0917
        self: object, stock: str, quantity: float, action: str,
        account: str, dry: bool = True, limit_price: float | None = None,  # noqa: FBT001, FBT002
    ) -> tuple[bool, str | None]:
        """Patched: fixes ICCM->ICCMX typeahead and 30s/attempt menu hang."""
        try:
            self.page.wait_for_load_state(state="load")  # type: ignore[attr-defined]
            if self.page.url != "https://digital.fidelity.com/ftgw/digital/trade-equity/index/orderEntry":  # type: ignore[attr-defined]
                self.page.goto("https://digital.fidelity.com/ftgw/digital/trade-equity/index/orderEntry")  # type: ignore[attr-defined]

            self.page.query_selector("#dest-acct-dropdown").click()  # type: ignore[attr-defined]
            account_locator = self.page.locator("button[role='option']").filter(  # type: ignore[attr-defined]
                has_text=account.upper(),
            )
            if not account_locator.is_visible():
                print("Reloading...")
                self.page.reload()  # type: ignore[attr-defined]
                self.page.query_selector("#dest-acct-dropdown").click()  # type: ignore[attr-defined]
            account_locator.click()
            self.page.wait_for_timeout(3000)  # type: ignore[attr-defined]

            # Enter the symbol
            self.page.get_by_label("Symbol", exact=True).click()  # type: ignore[attr-defined]
            self.page.get_by_label("Symbol", exact=True).fill(stock)  # type: ignore[attr-defined]
            # PATCH (Issue 1): Dismiss Fidelity's symbol-search typeahead
            # so the literal ticker is submitted on Enter. Without this,
            # ICCM is silently autocompleted to ICCMX (the mutual fund).
            # Escape is safe even when no dropdown is open.
            with contextlib.suppress(Exception):
                self.page.keyboard.press("Escape")  # type: ignore[attr-defined]
            self.page.get_by_label("Symbol", exact=True).press("Enter")  # type: ignore[attr-defined]

            # PATCH (Issue 1, defense-in-depth): Verify the Symbol
            # input's actual value matches what we typed. Substring
            # checks aren't reliable because ICCM is a prefix of
            # ICCMX — only the input's `value` attribute is
            # authoritative.
            self.page.locator("#quote-panel").wait_for(timeout=5000)  # type: ignore[attr-defined]
            with contextlib.suppress(Exception):
                input_value = self.page.get_by_label(  # type: ignore[attr-defined]
                    "Symbol", exact=True,
                ).input_value(timeout=2000)
                if (input_value or "").strip().upper() != stock.upper():
                    return (
                        False,
                        f"Symbol mismatch: typed {stock.upper()!r} but "
                        f"Symbol field shows {input_value!r} "
                        f"(typeahead substituted?). Aborting this account.",
                    )

            last_price = self.page.query_selector(  # type: ignore[attr-defined]
                "#eq-ticket__last-price > span.last-price",
            ).text_content()
            last_price = last_price.replace("$", "")

            if self.page.get_by_role("button", name="View expanded ticket").is_visible():  # type: ignore[attr-defined]
                self.page.get_by_role("button", name="View expanded ticket").click()  # type: ignore[attr-defined]
                self.page.get_by_role("button", name="Calculate shares").wait_for(timeout=5000)  # type: ignore[attr-defined]

            extended = False
            precision = 3
            extended_wrapper = self.page.locator(".eq-ticket__extendedhour-toggle")  # type: ignore[attr-defined]
            extended_btn = self.page.locator("#eq-ticket_extendedhour")  # type: ignore[attr-defined]

            if extended_btn.is_visible():
                class_attr = extended_wrapper.first.get_attribute("class")
                if class_attr and "pvd-switch--on" in class_attr:
                    print("Extended Hours Trading is already active.")
                else:
                    print("Enabling Extended Hours Trading...")
                    extended_btn.click()
                    self.page.wait_for_timeout(1000)  # type: ignore[attr-defined]
                extended = True
                precision = 2
                if self.page.locator("#eq-ticket__last-price > span.last-price").is_visible():  # type: ignore[attr-defined]
                    new_price = self.page.query_selector(  # type: ignore[attr-defined]
                        "#eq-ticket__last-price > span.last-price",
                    ).text_content()
                    last_price = new_price.replace("$", "").replace(",", "")
            elif self.page.get_by_text("Extended hours trading").is_visible():  # type: ignore[attr-defined]
                if self.page.get_by_text("Extended hours trading: OffUntil 8:00 PM ET").is_visible():  # type: ignore[attr-defined]
                    self.page.get_by_text("Extended hours trading: OffUntil 8:00 PM ET").check()  # type: ignore[attr-defined]
                extended = True
                precision = 2

            # Action dropdown (Buy/Sell)
            action_dropdown = self.page.locator(".eq-ticket-action-label")  # type: ignore[attr-defined]
            target_option = self.page.get_by_role("option", name=action.lower().title(), exact=True)  # type: ignore[attr-defined]

            # PATCH (Issue 2): Tighten the dropdown-click timeout so
            # every attempt fails fast in ~3s instead of the
            # Playwright default 30s. Without this, an account with a
            # stuck/bad page state burns ~150s before giving up.
            for attempt in range(5):
                try:
                    if not target_option.is_visible():
                        action_dropdown.click(force=True, timeout=3000)
                        self.page.wait_for_timeout(500)  # type: ignore[attr-defined]
                    target_option.click(timeout=3000)
                    break
                except (PlaywrightTimeoutError, Exception) as e:
                    print(f"Attempt {attempt + 1} failed to click '{action}': {e}")
                    print("Re-opening menu and retrying...")
                    self.page.wait_for_timeout(1000)  # type: ignore[attr-defined]
                    # PATCH (Issue 2): After two consecutive failures,
                    # reload the trade page once to reset the
                    # underlying state. This handles the
                    # genuinely-stuck case (vs the merely-slow case).
                    if attempt == 1:
                        with contextlib.suppress(Exception):
                            self.page.reload()  # type: ignore[attr-defined]
                            self.page.wait_for_timeout(2000)  # type: ignore[attr-defined]
                            # Re-enter the account + symbol on reload.
                            self.page.query_selector("#dest-acct-dropdown").click()  # type: ignore[attr-defined]
                            account_locator.click()
                            self.page.wait_for_timeout(2000)  # type: ignore[attr-defined]
                            self.page.get_by_label("Symbol", exact=True).click()  # type: ignore[attr-defined]
                            self.page.get_by_label("Symbol", exact=True).fill(stock)  # type: ignore[attr-defined]
                            self.page.keyboard.press("Escape")  # type: ignore[attr-defined]
                            self.page.get_by_label("Symbol", exact=True).press("Enter")  # type: ignore[attr-defined]
                            self.page.locator("#quote-panel").wait_for(timeout=5000)  # type: ignore[attr-defined]
            else:
                return (False, f"Could not select '{action}' after 5 attempts. Menu stuck.")

            # Quantity
            self.page.locator("#eqt-mts-stock-quatity div").filter(has_text="Quantity").click()  # type: ignore[attr-defined]
            self.page.get_by_text("Quantity", exact=True).fill(str(quantity))  # type: ignore[attr-defined]

            # Limit vs market
            if float(last_price) < 1 or extended or limit_price is not None:
                if limit_price is not None:
                    wanted_price = limit_price
                elif action.lower() == "buy":
                    difference_price = 0.01 if float(last_price) > 0.1 else 0.0001  # noqa: PLR2004
                    wanted_price = round(float(last_price) + difference_price, precision)
                else:
                    difference_price = 0.01 if float(last_price) > 0.1 else 0.0001  # noqa: PLR2004
                    wanted_price = round(float(last_price) - difference_price, precision)
                self.page.query_selector("#dest-dropdownlist-button-ordertype > span:nth-child(1)").click()  # type: ignore[attr-defined]
                self.page.get_by_role("option", name="Limit", exact=True).click()  # type: ignore[attr-defined]
                self.page.get_by_text("Limit price", exact=True).click()  # type: ignore[attr-defined]
                self.page.get_by_label("Limit price").fill(str(wanted_price))  # type: ignore[attr-defined]
            else:
                self.page.locator("#order-type-container-id").click()  # type: ignore[attr-defined]
                self.page.get_by_role("option", name="Market", exact=True).click()  # type: ignore[attr-defined]

            self.page.get_by_role("button", name="Preview order").click()  # type: ignore[attr-defined]
            self.wait_for_loading_sign()  # type: ignore[attr-defined]

            # Error handling on the preview
            try:
                self.page.get_by_role("button", name="Place order", exact=False).wait_for(  # type: ignore[attr-defined]
                    timeout=5000, state="visible",
                )
            except PlaywrightTimeoutError:
                error_message = ""
                filtered_error = ""
                error_box_closed = False
                with contextlib.suppress(Exception):
                    error_message = (
                        self.page.get_by_label("Error").locator("div")  # type: ignore[attr-defined]
                        .filter(has_text="critical").nth(2).text_content(timeout=2000)
                    )
                    self.page.get_by_role("button", name="Close dialog").click()  # type: ignore[attr-defined]
                    error_box_closed = True
                if not error_message:
                    with contextlib.suppress(Exception):
                        error_message = self.page.wait_for_selector(  # type: ignore[attr-defined]
                            '.pvd-inline-alert__content font[color="red"]',
                            timeout=2000,
                        ).text_content()
                        self.page.get_by_role("button", name="Close dialog").click()  # type: ignore[attr-defined]
                        error_box_closed = True
                if error_message:
                    for i, character in enumerate(error_message):
                        if (
                            (character == " " and error_message[i - 1] == " ")
                            or character in {"\n", "\t"}
                        ):
                            continue
                        filtered_error += character
                    error_message = filtered_error.replace("critical", "").strip().replace("\n", "")
                else:
                    error_message = "Could not retrieve error message from popup"
                if not error_box_closed:
                    self.page.reload()  # type: ignore[attr-defined]
                return (False, error_message)

            # Preview validation
            if (
                not self.page.locator("preview").filter(has_text=account.upper()).is_visible()  # type: ignore[attr-defined]
                or not self.page.get_by_text(f"Symbol{stock.upper()}", exact=True).is_visible()  # type: ignore[attr-defined]
                or not self.page.get_by_text(f"Action{action.lower().title()}").is_visible()  # type: ignore[attr-defined]
                or not self.page.get_by_text(f"Quantity{quantity}").is_visible()  # type: ignore[attr-defined]
            ):
                return (False, "Order preview is not what is expected")

            if not dry:
                self.page.get_by_role("button", name="Place order", exact=False).first.click()  # type: ignore[attr-defined]
                try:
                    self.wait_for_loading_sign()  # type: ignore[attr-defined]
                    self.page.get_by_text("Order received", exact=True).wait_for(  # type: ignore[attr-defined]
                        timeout=10000, state="visible",
                    )
                    return (True, None)  # noqa: TRY300
                except PlaywrightTimeoutError as toe:
                    return (False, f"Timed out waiting for 'Order received': {toe}")
            return (True, None)  # noqa: TRY300
        except PlaywrightTimeoutError as toe:
            return (False, f"Driver timed out. Order not complete: {toe}")
        except Exception as e:
            return (False, f"Some error occurred: {e}")

    _f.FidelityAutomation.transaction = transaction  # type: ignore[invalid-assignment]
    _applied = True
    print("Fidelity: ICCMX+buy-button patch active")
