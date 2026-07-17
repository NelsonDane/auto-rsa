# Kenneth Tang
# API to Interface with Fidelity
# Uses headless Playwright
# 2024/09/19
# Adapted from Nelson Dane's Selenium based code and created with the help of playwright codegen

import asyncio
import contextlib
import datetime
import os
import traceback
from pathlib import Path
from typing import cast

from discord.ext.commands import Bot
from dotenv import load_dotenv
from fidelity import fidelity

from src.brokerages import _fidelity_afterhours_limit, _fidelity_iccmx_and_buy_button, _fidelity_modal_dismiss, _fidelity_patchright
from src.helper_api import Brokerage, StockOrder, account_allowed, get_otp_from_discord, mask_string, print_all_holdings, print_and_discord
from src.ledger import Play, mark_result, record_intent

# Swap fidelity-api's detectable browser engine for patchright before
# any FidelityAutomation is constructed, and stop a single rejected
# order from cascading 30s timeouts into every following account.
_fidelity_patchright.apply()
# Apply BEFORE the modal-dismiss / afterhours wrappers so those wrap
# the fixed transaction (symbol typeahead + fast-fail action menu).
_fidelity_iccmx_and_buy_button.apply()
_fidelity_modal_dismiss.apply()
# Applied last so it is the OUTERMOST transaction wrapper: its retry
# goes back through the modal-dismiss cleanup on the second attempt.
_fidelity_afterhours_limit.apply()


def _fidelity_diagnostic(fidelity_browser: object, name: str) -> None:
    """Dump the current Fidelity page (screenshot + visible text) on failure.

    The 2FA flow can't be fixed blind: this captures exactly what
    Fidelity shows (method chooser, button labels, headings) so the
    login/2FA navigation can be corrected against the real DOM. The
    .txt is scrubbed of long tokens by the runner's log redaction only
    for the log; the file itself is local under the gitignored cwd.
    Best-effort; never raises.
    """
    try:
        page = fidelity_browser.page  # type: ignore[attr-defined]
        stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
        base = f"fidelity-error-{name.replace(' ', '_')}-{stamp}"
        # Screenshot only when explicitly opted in. It used to save a
        # full-page PNG on every Fidelity error (which, since login
        # succeeds and a later step trips, captured the accounts page) —
        # the operator asked to stop those pictures now that login is
        # stable. Set RSA_FIDELITY_DIAGNOSTIC=1 to re-enable it for
        # debugging. The lightweight text dump (URL + visible text) is
        # still written and is enough to diagnose most DOM changes.
        wrote_png = False
        if os.getenv("RSA_FIDELITY_DIAGNOSTIC") == "1":
            with contextlib.suppress(Exception):
                page.screenshot(path=f"{base}.png", full_page=True)
                wrote_png = True
        body = ""
        with contextlib.suppress(Exception):
            body = page.inner_text("body")
        Path(f"{base}.txt").write_text(
            f"URL: {getattr(page, 'url', '?')}\n\n--- visible text ---\n{body}\n",
            encoding="utf-8",
        )
        png_note = f"{base}.png / " if wrote_png else ""
        print(f"Saved Fidelity diagnostic: {png_note}{base}.txt")
    except Exception as exc:
        print(f"(Fidelity diagnostic capture failed: {exc})")


def fidelity_run(
    order_obj: StockOrder,
    bot_obj: Bot | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    """Entry point from main function. Gathers credentials and go through commands for each set of credentials found in the FIDELITY env variable."""
    # Initialize .env file
    load_dotenv()
    # Import Chase account
    if not os.getenv("FIDELITY"):
        print("Fidelity not found, skipping...")
        return
    accounts = os.environ["FIDELITY"].strip().split(",")
    # Get headless flag
    headless = os.getenv("HEADLESS", "true").lower() == "true"

    # For each set of login info, i.e. separate chase accounts
    for account in accounts:
        # Start at index 1 and go to how many logins we have
        index = accounts.index(account) + 1
        name = f"Fidelity {index}"
        # Receive the chase broker class object and the AllAccount object related to it
        fidelityobj = fidelity_init(
            account=account,
            name=name,
            headless=headless,
            bot_obj=bot_obj,
            loop=loop,
        )
        if fidelityobj is not None:
            # Store the Brokerage object for fidelity under 'fidelity' in the orderObj
            order_obj.set_logged_in(fidelityobj, "fidelity")
            if order_obj.get_holdings():
                fidelity_holdings(fidelityobj, name, loop=loop)
            # Only other option is _transaction
            else:
                fidelity_transaction(fidelityobj, name, order_obj, loop=loop)
    return


def fidelity_init(account: str, name: str, *, headless: bool = True, bot_obj: Bot | None = None, loop: asyncio.AbstractEventLoop | None = None) -> Brokerage | None:  # noqa: C901
    """Log into fidelity. Creates a fidelity brokerage object and a FidelityAutomation object.

    The FidelityAutomation object is stored within the brokerage object and some account information
    is gathered.
    """
    # Log into Fidelity account
    print("Logging into Fidelity...")

    # Create brokerage class object and call it Fidelity
    fidelity_obj = Brokerage("Fidelity")
    fidelity_browser = None

    try:
        # Split the login into into separate items
        account_creds = account.split(":")
        # Create a Fidelity browser object
        fidelity_browser = fidelity.FidelityAutomation(
            headless=headless,
            title=name,
            profile_path="./creds",
        )

        # Log into fidelity
        step_1, step_2 = fidelity_browser.login(
            account_creds[0],
            account_creds[1],
            account_creds[2] if len(account_creds) > 2 else "NA",  # noqa: PLR2004
        )
        # If 2FA is present, ask for code
        if step_1 and not step_2:
            # Unattended (headless scheduler) can't answer an SMS prompt
            # and a bare input() would hang the run forever. Escalate
            # with an actionable message so the executor skips+alerts
            # instead of blocking. Configure the Fidelity TOTP secret so
            # the vendored lib logs in automatically (no SMS at all).
            if os.getenv("RSA_UNATTENDED") == "1":
                msg = (
                    f"{name}: Fidelity requires SMS 2FA but is running "
                    f"unattended with no TOTP secret. Add the Fidelity "
                    f"TOTP secret to credentials for automatic login."
                )
                raise Exception(msg, loop)
            if bot_obj is None and loop is None:
                fidelity_browser.login_2FA(input("Enter code: "))
            elif bot_obj is not None and loop is not None:
                # Should wait for 60 seconds before timeout
                sms_code = asyncio.run_coroutine_threadsafe(
                    get_otp_from_discord(bot_obj, name, code_len=6, loop=loop),
                    loop,
                ).result()
                if sms_code is None:
                    msg = f"{name}: No SMS code found"
                    raise Exception(msg, loop)
                fidelity_browser.login_2FA(sms_code)
        elif not step_1:
            msg = f"{name}: Login Failed. Got Error Page: Current URL: {fidelity_browser.page.url}"
            raise Exception(msg, loop)

        # By this point, we should be logged in so save the driver
        fidelity_obj.set_logged_in_object(name, fidelity_browser)

        # Getting account numbers, names, and balances
        account_dict = fidelity_browser.getAccountInfo()

        if account_dict is None:
            msg = f"{name}: Error getting account info"
            raise Exception(msg, loop)
        # Set info into fidelity brokerage object
        for acct in account_dict:
            fidelity_obj.set_account_number(name, acct)
            fidelity_obj.set_account_type(name, acct, account_dict[acct]["nickname"])
            fidelity_obj.set_account_totals(name, acct, account_dict[acct]["balance"])
        print(f"Logged in to {name}!")

    except Exception as e:
        print(f"Error logging in to Fidelity: {e}")
        print(traceback.format_exc())
        if fidelity_browser is not None:
            _fidelity_diagnostic(fidelity_browser, name)
        return None
    else:
        return fidelity_obj


def fidelity_holdings(fidelity_o: Brokerage, name: str, loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Get the holdings per account by reading from the previously downloaded positions csv file.

    Prints holdings for each account and provides a summary if the user has more than 5 accounts.
    """
    # Get the browser back from the fidelity object
    fidelity_browser = cast("fidelity.FidelityAutomation", fidelity_o.get_logged_in_objects(name))
    account_dict = fidelity_browser.account_dict
    for account_number in account_dict:
        for d in account_dict[account_number]["stocks"]:
            # Append the ticker to the appropriate account
            fidelity_o.set_holdings(
                parent_name=name,
                account_name=account_number,
                stock=d["ticker"],
                quantity=d["quantity"],
                price=d["last_price"],
            )

    # Print to console and to discord
    print_all_holdings(fidelity_o, loop)

    # Close browser
    fidelity_browser.close_browser()


def fidelity_transaction(
    fidelity_o: Brokerage,
    name: str,
    order_obj: StockOrder,
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    """Call FidelityAutomation.transaction() and process its return."""
    # Get the driver
    fidelity_browser = cast("fidelity.FidelityAutomation", fidelity_o.get_logged_in_objects(name))
    # Get full list of accounts in case some had no holdings
    fidelity_browser.get_list_of_accounts()
    # An explicit numeric price -> a real Fidelity limit order at that
    # price (required after hours; market orders are rejected, 030910).
    # "limit"/"market" strings -> let fidelity-api use its own native
    # logic (sub-$1 / extended-hours auto-price); we never invent a
    # real-money price.
    order_price = order_obj.get_price()
    limit_price = float(order_price) if isinstance(order_price, (int, float)) else None
    # Go trade
    for stock in order_obj.get_stocks():
        # Say what we are doing
        print_and_discord(
            f"{name}: {order_obj.get_action()}ing {order_obj.get_amount()} of {stock}",
            loop,
        )
        # Reload the page incase we were trading before
        fidelity_browser.page.reload()
        for account_number in fidelity_browser.account_dict:
            # If we are selling, check to see if the account has the stock to sell
            if order_obj.get_action().lower() == "sell" and stock not in fidelity_browser.get_stocks_in_account(account_number):
                # Doesn't have it, skip account
                continue

            print_account = mask_string(account_number)
            # Global per-broker sub-account allow-list (RSA_ACCOUNT_FILTER).
            if not account_allowed("fidelity", account_number, order_obj.get_action()):
                print_and_discord(
                    f"{name} account {print_account}: skipped {stock} (not in account filter)",
                    loop,
                )
                continue
            # Idempotency: reserve this play before ordering so a retry,
            # crash-resume, or re-queued signal can't buy the share twice.
            # Manual runs get a synthetic key; the signal path supplies
            # RSA_PLAY_KEY (per-source) and RSA_PLAY_SPLIT_KEY (economic,
            # producer-agnostic — blocks the same real split bought via a
            # different feed). Dry runs are never recorded.
            play = Play(
                key=os.getenv("RSA_PLAY_KEY") or f"MANUAL:{stock}:{order_obj.get_action().lower()}",
                broker="fidelity",
                account=str(account_number),
                ticker=stock,
                action=order_obj.get_action(),
                split_key=os.getenv("RSA_PLAY_SPLIT_KEY", ""),
            )
            if not order_obj.get_dry() and not record_intent(play, order_obj.get_amount()):
                print_and_discord(
                    f"{name} account {print_account}: skipped {stock} "
                    "(ledger: already executed or in-flight — no double-buy)",
                    loop,
                )
                continue

            # Go trade for all accounts for that stock
            success, error_message = cast(
                "tuple[bool, str | None]",
                fidelity_browser.transaction(
                    stock,
                    order_obj.get_amount(),
                    order_obj.get_action(),
                    account_number,
                    order_obj.get_dry(),
                    limit_price,  # type: ignore[invalid-argument-type]
                ),
            )
            if not order_obj.get_dry():
                mark_result(play, success=success, detail=str(error_message or ""))
            # Report error if occurred
            if not success:
                print_and_discord(
                    f"{name} account {print_account}: Error: {error_message}",
                    loop,
                )
            # Print test run confirmation if test run
            elif success and order_obj.get_dry():
                print_and_discord(
                    f"DRY: {name} account {print_account}: {order_obj.get_action()} {order_obj.get_amount()} shares of {stock}",
                    loop,
                )
            # Print real run confirmation if real run
            elif success and not order_obj.get_dry():
                print_and_discord(
                    f"{name} account {print_account}: {order_obj.get_action()} {order_obj.get_amount()} shares of {stock}",
                    loop,
                )

    # Close browser
    fidelity_browser.close_browser()
