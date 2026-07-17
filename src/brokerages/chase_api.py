# Donald Ryan Gullett(MaxxRK)
# Chase API

import asyncio
import contextlib
import datetime
import os
import pprint
import traceback
from pathlib import Path
from typing import cast

import psutil
from chase import account as ch_account
from chase import order, session, symbols
from discord.ext.commands import Bot
from dotenv import load_dotenv

from src.brokerages import (
    _chase_account_scoped_order,
    _chase_direct_order,
    _chase_holdings_capture,
    _chase_request_timeout,
)
from src.helper_api import Brokerage, StockOrder, complete_or_fail, get_otp_from_discord, print_all_holdings, print_and_discord, reserve_or_skip

# Harden the upstream holdings capture, which times out silently (10s,
# exact-match XHR) on the degraded post-mobile-approval session.
_chase_holdings_capture.apply()
# Opt-in (RSA_CHASE_DIRECT_ORDER=1): replace _place_order_async with
# a direct-POST version that skips the hang-prone browser page nav.
# Must run before the timeout patch so the watchdog still wraps it.
_chase_direct_order.apply()
# Bound the vendored order validate/execute POSTs (curl_cffi, no
# timeout) so a stuck Chase order can't freeze the run.
_chase_request_timeout.apply()
# Navigate the order page account-scoped (…/entry;ai={id}) so a
# multi-account login doesn't stall on Chase's "Choose an account".
_chase_account_scoped_order.apply()


def _cleanup_stale_chase_browsers(creds_dir: str = "./creds") -> None:
    """Free a leaked Chase browser WITHOUT wiping its saved session.

    The upstream chase library's close_browser can fall back to an
    un-awaited asyncio task, leaving a zombie Chrome that keeps
    ``creds/chase_*`` locked ("Failed to connect to browser" on the
    next run). This kills only browser processes whose command line
    references the auto-rsa Chase profile path, then clears just the
    Chrome *singleton lock* files so the profile can be reopened.

    It deliberately KEEPS the profile directory (cookies / remembered
    device) so a subsequent run skips the mobile-app 2FA approval.
    Never touches vault.json or other brokers' data; never raises.
    """
    try:
        root = Path(creds_dir).resolve()
        marker = str(root).lower()
        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                name = (proc.info["name"] or "").lower()
                if not ("chrome" in name or "chromedriver" in name):
                    continue
                cmdline = " ".join(proc.info["cmdline"] or []).lower()
                # Only our Chase profile dirs — never the user's own Chrome.
                if marker in cmdline and "chase" in cmdline:
                    proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
                continue
        # Clear only the stale lock files left by the killed zombie so
        # Chrome will reopen the SAME profile (preserving the session).
        for profile in root.glob("chase_*"):
            if not profile.is_dir():
                continue
            for lock in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
                with contextlib.suppress(OSError):
                    (profile / lock).unlink(missing_ok=True)
    except Exception as exc:
        print(f"Chase cleanup skipped: {exc}")


def chase_run(order_obj: StockOrder, bot_obj: Bot | None = None, loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Run all of the Chase API commands in a single function."""
    # Initialize .env file
    load_dotenv()
    # Import Chase account
    if not os.getenv("CHASE"):
        print("Chase not found, skipping...")
        return
    accounts = os.environ["CHASE"].strip().split(",")
    # Clear any leaked Chrome/profile from a prior run so zendriver can
    # start (scoped to creds/chase_* only — never vault.json).
    _cleanup_stale_chase_browsers()
    # Get headless flag
    headless = os.getenv("HEADLESS", "true").lower() == "true"

    # For each set of login info, i.e. seperate chase accounts
    for account in accounts:
        # Start at index 1 and go to how many logins we have
        index = accounts.index(account) + 1
        # Receive the chase broker class object and the AllAccount object related to it
        chase_details = chase_init(
            account=account,
            index=index,
            headless=headless,
            bot_obj=bot_obj,
            loop=loop,
        )
        if chase_details is not None:
            order_obj.set_logged_in(chase_details[0], "chase")
            if order_obj.get_holdings():
                chase_holdings(chase_details[0], chase_details[1], loop=loop)
            # Only other option is _transaction
            else:
                chase_transaction(
                    chase_details[0],
                    chase_details[1],
                    order_obj,
                    loop=loop,
                )
    return


def get_account_id(account_connectors: dict[str, str] | None, value: str) -> str | None:
    """Retrieve the account ID associated with a given value."""
    if account_connectors is None:
        return None
    for key, val in account_connectors.items():
        if val[0] == value:
            return str(key)
    return None


def _chase_2fa_needs_code(ch_session: object) -> bool:
    """Report whether Chase is on the texted-code step (an #otpInput exists).

    Distinguishes the SMS path (has a code box) from the "Confirm using
    our mobile app" push path (no code box). Best-effort: on any probe
    failure we default to True so the user is still asked for a code
    (the pre-existing, never-worse behaviour) rather than silently
    skipping a code that was actually required.
    """

    async def _probe() -> bool:
        try:
            element = await ch_session.page.find("#otpInput", timeout=8)  # type: ignore[attr-defined]
        except Exception:
            return False
        return element is not None

    try:
        return bool(ch_session.loop.run_until_complete(_probe()))  # type: ignore[attr-defined]
    except Exception:
        return True


def chase_init(account: str, index: int, *, headless: bool = True, bot_obj: Bot | None = None, loop: asyncio.AbstractEventLoop | None = None) -> tuple[Brokerage, ch_account.AllAccount] | None:
    """Log into chase. Checks for 2FA and gathers details on the chase accounts."""
    # Log in to Chase account
    print("Logging in to Chase...")
    # Create brokerage class object and call it chase_obj
    chase_obj = Brokerage("Chase")
    name = f"Chase {index}"
    ch_session: session.ChaseSession | None = None
    try:
        # Split the login into into seperate items
        user_pass = account.split(":")
        # If the debug flag is present, use it, else set it to false
        debug = bool(user_pass[3]) if len(user_pass) == 4 else False  # noqa: PLR2004
        # Create a ChaseSession class object which automatically configures and opens a browser
        ch_session = session.ChaseSession(
            title=f"chase_{index}",
            headless=headless,
            profile_path="./creds",
            debug=debug,
        )
        # Login to chase
        need_second = ch_session.login(user_pass[0], user_pass[1], int(user_pass[2]))
        # If 2FA is present, ask for code.
        # Chase returns need_second for BOTH 2FA paths: a texted code
        # AND "Confirm using our mobile app" push approval. Only the
        # texted path has a code field (#otpInput); the push path has
        # no code at all -- login_two ignores its argument and polls
        # ~60-90s for the post-approval landing page. So for push we
        # don't prompt at all: just wait while the user taps Approve on
        # their phone (no tedious "submit blank" step). We only block
        # for input on the texted path, where a code really is needed.
        if need_second:
            if bot_obj is None and loop is None:
                if _chase_2fa_needs_code(ch_session):
                    ch_session.login_two(
                        input("Enter the Chase code from your TEXT message: "),
                    )
                else:
                    print(
                        "Chase sent a sign-in request to your MOBILE APP. "
                        "Approve it on your phone now -- waiting up to ~90s, "
                        "no action needed here.",
                    )
                    ch_session.login_two("")
            elif bot_obj is not None and loop is not None:
                sms_code = asyncio.run_coroutine_threadsafe(
                    get_otp_from_discord(bot_obj, name, code_len=8, loop=loop),
                    loop,
                ).result()
                if sms_code is None:
                    msg = f"Chase {index} code not received in time..."
                    raise Exception(msg, loop)
                ch_session.login_two(sms_code)
        # Create an AllAccounts class object using the current browser session. Holds information about all accounts
        all_accounts = ch_account.AllAccount(ch_session)
        # Get the account IDs and store in a list. The IDs are different than account numbers.
        account_ids = list([] if all_accounts.account_connectors is None else all_accounts.account_connectors.keys())
        print("Logged in to Chase!")
        # In the Chase Brokerage object, set the index of "Chase 1" to be its own empty array and append the chase session to the end of this array
        chase_obj.set_logged_in_object(name, ch_session)
        # Create empty array to store account number masks (last 4 digits of each account number)
        print_accounts = []
        for acct in account_ids:
            # Create an AccountDetails Object which organizes the information in the AllAccounts class object
            chase_account = ch_account.AccountDetails(acct, all_accounts)
            # Save account masks
            chase_obj.set_account_number(name, chase_account.mask)
            chase_obj.set_account_totals(name, chase_account.mask, chase_account.account_value)
            print_accounts.append(chase_account.mask)
        print(f"The following Chase accounts were found: {print_accounts}")
    except Exception as e:
        if ch_session:
            _chase_diagnostic(ch_session, name)  # capture BEFORE closing
            ch_session.close_browser()
        print(f"Error logging in to Chase: {e}")
        print(traceback.format_exc())
        return None
    return (chase_obj, all_accounts)


def _chase_diagnostic(ch_session: object, name: str) -> None:
    """Dump the current Chase page (screenshot + visible text) on failure.

    Lets us see the real post-2FA / push-approval interstitial that the
    upstream library doesn't navigate, so it can be fixed against the
    actual DOM. Best-effort; never raises. Must run before
    close_browser().
    """
    try:
        page = ch_session.page  # type: ignore[attr-defined]
        loop = ch_session.loop  # type: ignore[attr-defined]
        stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
        base = f"chase-error-{name.replace(' ', '_')}-{stamp}"
        with contextlib.suppress(Exception):
            loop.run_until_complete(page.save_screenshot(f"{base}.png"))
        body = ""
        with contextlib.suppress(Exception):
            body = loop.run_until_complete(page.evaluate("document.body.innerText"))
        Path(f"{base}.txt").write_text(
            f"URL: {getattr(page, 'url', '?')}\n\n--- visible text ---\n{body}\n",
            encoding="utf-8",
        )
        print(f"Saved Chase 2FA diagnostic: {base}.png / {base}.txt")
    except Exception as exc:
        print(f"(Chase diagnostic capture failed: {exc})")


def _process_position(position: dict, chase_o: Brokerage, key: str, account: str) -> None:
    """Process a single position and add it to holdings."""
    if position["instrumentLongName"] == "Cash and Sweep Funds":
        sym = position["instrumentLongName"]
        current_price = position["marketValue"]["baseValueAmount"]
        qty = "1"
        chase_o.set_holdings(key, account, sym, qty, current_price)
    elif position["assetCategoryName"] == "EQUITY":
        try:
            sym = position["positionComponents"][0]["securityIdDetail"][0]["symbolSecurityIdentifier"]
            current_price = position["marketValue"]["baseValueAmount"]
            qty = position["tradedUnitQuantity"]
        except KeyError:
            sym = position["securityIdDetail"]["cusipIdentifier"]
            current_price = position["marketValue"]["baseValueAmount"]
            qty = position["tradedUnitQuantity"]
        chase_o.set_holdings(key, account, sym, qty, current_price)


def _process_account_holdings(chase_o: Brokerage, all_accounts: ch_account.AllAccount, key: str, account: str) -> None:
    """Process holdings for a single account."""
    ch_session = cast("session.ChaseSession", chase_o.get_logged_in_objects(key))
    account_id = get_account_id(all_accounts.account_connectors, account)
    if account_id:
        data = symbols.SymbolHoldings(account_id, ch_session)
        if data.get_holdings():
            for position in data.positions:
                _process_position(position, chase_o, key, account)


def chase_holdings(chase_o: Brokerage, all_accounts: ch_account.AllAccount, loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Retrieve and display all Chase account holdings."""
    # Get holdings on each account. This loop only ever runs once.
    ch_session: session.ChaseSession | None = None
    # Get the session object
    account = ""
    for key in chase_o.get_account_numbers():
        try:
            ch_session = cast("session.ChaseSession", chase_o.get_logged_in_objects(key))
            # Retrieve account masks and iterate through them
            for _, account in enumerate(chase_o.get_account_numbers(key)):
                _process_account_holdings(chase_o, all_accounts, key, account)
        except Exception as e:
            if ch_session:
                ch_session.close_browser()
            print_and_discord(
                f"{key} {account}: Error getting holdings: {type(e).__name__}: {e!r}",
                loop,
            )
            print(traceback.format_exc())
            continue
        print_all_holdings(chase_o, loop)
    if ch_session:
        print_and_discord("Closing Chase browser...", loop)
        ch_session.close_browser()


def _calculate_limit_price(symbol_quote: symbols.SymbolQuote, action: str) -> tuple[order.PriceType, float]:
    """Calculate limit price for buy orders."""
    current_price = symbol_quote.ask_price

    if current_price >= 1.00:
        return order.PriceType.MARKET, 0.0
    if action.upper() == "BUY":
        # For buys, always round UP to ensure fill
        limit_price = round(current_price + 0.01, 2)
    else:  # SELL
        # For sells, always round DOWN to ensure fill
        limit_price = round(current_price - 0.01, 2)
        limit_price = max(limit_price, 0.01)
    return order.PriceType.LIMIT, limit_price


def _process_order_messages(messages: dict, order_obj: StockOrder, key: str, account: str, loop: asyncio.AbstractEventLoop | None) -> None:
    """Process and print order messages."""
    if order_obj.get_dry():
        pprint.pprint(messages["ORDER VALIDATION"])  # noqa: T203
        print_and_discord(
            (f"{key} account {account}: The order verification was " + ("successful" if messages["ORDER VALIDATION"] else "unsuccessful")),
            loop,
        )
        if messages["ORDER INVALID"]:
            print_and_discord(
                f"{key} account {account}: The order verification produced the following messages: {messages['ORDER INVALID']}",
                loop,
            )
    else:
        # Check if ORDER CONFIRMATION is a dict or string
        order_confirmation = messages["ORDER CONFIRMATION"]
        is_successful = bool(order_confirmation.get("orderIdentifier")) if isinstance(order_confirmation, dict) else isinstance(order_confirmation, str) and len(order_confirmation) > 0
        if is_successful:
            oid = (
                order_confirmation.get("orderIdentifier")
                if isinstance(order_confirmation, dict) else order_confirmation
            )
            queued = (
                bool(order_confirmation.get("orderQueueAvailabilityIndicator"))
                if isinstance(order_confirmation, dict) else False
            )
            # A queued order is placed but not yet filled — it sits until the
            # next market session and fills only if the limit is reached. Say
            # so, so a placed order isn't mistaken for a failed one.
            note = (
                " — QUEUED for the next market session (fills when the limit "
                "is reached; shares appear after it fills)"
                if queued else ""
            )
            print_and_discord(
                f"{key} account {account}: ✅ Order placed (Chase order id "
                f"{oid}){note}.",
                loop,
            )
        else:
            print_and_discord(
                f"{key} account {account}: ❌ The order was unsuccessful",
                loop,
            )
        if messages["ORDER INVALID"]:
            print_and_discord(
                f"{key} account {account}: The order produced the following messages: {messages['ORDER INVALID']}",
                loop,
            )


def _flatten_chase_error(invalid: object) -> str:
    """Render Chase's ORDER INVALID as a single readable line.

    Chase returns ``tradeErrorMessages`` as a list and the upstream
    library shoves that list straight into ``ORDER INVALID``. The
    GUI then shows ``['Trade rejected: insufficient buying power']``
    — operator-confusing. Flatten lists to ``"; "``-joined strings
    so the displayed reason reads like a sentence.
    """
    if not invalid:
        return ""
    if isinstance(invalid, list):
        return "; ".join(str(m) for m in invalid if m)
    return str(invalid)


def _verify_chase_response(
    messages: dict, *, symbol: str, quantity: int, action: str,
) -> str:
    """Defense-in-depth: confirm Chase's response matches the request.

    Returns an empty string on match (or when there's nothing to
    verify), or a human-readable mismatch description on failure —
    same shape as the Fidelity Symbol-mismatch guard. If Chase's
    validation/confirmation echoes back a different ticker, qty, or
    side than we asked for, treat the order as FAILED regardless of
    what ORDER CONFIRMATION says.

    Operates on whichever of ORDER CONFIRMATION (live) or
    ORDER VALIDATION (dry run) is populated. Both are dicts when
    Chase returned cleanly; either may be empty string when the
    order short-circuited at validation.
    """
    confirmation = (
        messages.get("ORDER CONFIRMATION")
        or messages.get("ORDER VALIDATION")
    )
    if not isinstance(confirmation, dict):
        return ""

    resp_symbol = str(confirmation.get("securitySymbolCode", "")).upper().strip()
    if resp_symbol and resp_symbol != symbol.upper().strip():
        return (
            f"Chase returned wrong symbol: "
            f"asked {symbol.upper()!r}, got {resp_symbol!r}"
        )

    resp_qty = confirmation.get("orderQuantity")
    if resp_qty is not None:
        try:
            if int(resp_qty) != int(quantity):
                return (
                    f"Chase returned wrong quantity: "
                    f"asked {quantity}, got {resp_qty}"
                )
        except (TypeError, ValueError):
            pass  # unparseable qty — don't block on a serialization quirk

    resp_action = str(confirmation.get("tradeActionName", "")).upper().strip()
    if resp_action and resp_action != action.upper().strip():
        return (
            f"Chase returned wrong action: "
            f"asked {action.upper()!r}, got {resp_action!r}"
        )

    return ""


def _order_succeeded(messages: dict, *, dry: bool) -> bool:
    """Decide whether the ledger should record an order as EXECUTED.

    Dry runs legitimately have only ORDER VALIDATION and no execute,
    so a truthy validation is sufficient there.

    For LIVE orders: ORDER CONFIRMATION is set ONLY when the execute
    POST returned HTTP 2xx with a JSON body (see
    _chase_direct_order._direct_place_order_async — a non-2xx or a
    transport failure leaves it "" and sets ORDER INVALID instead,
    so success is already False upstream). A truthy ORDER VALIDATION
    alone must NOT count: it's populated before the irreversible
    execute, so trusting it would mark a never-executed order
    EXECUTED.

    We deliberately DON'T require a specific order-id key. The exact
    execute-response shape isn't confirmed against live Chase, and
    the previous strict id-key check risked the WORSE failure: a
    real fill whose id lives under an unexpected key gets recorded
    FAILED, then the next run re-submits (double-buy). A non-empty
    ORDER CONFIRMATION dict (i.e. a 2xx execute with a body) that
    carries no explicit reject/error marker is treated as a fill.
    Empty/degenerate bodies and explicit rejects still fail.
    """
    if dry:
        return bool(messages.get("ORDER VALIDATION"))
    confirmation = messages.get("ORDER CONFIRMATION")
    if not isinstance(confirmation, dict) or not confirmation:
        return False
    # If Chase echoed an explicit rejection inside a 2xx body, fail.
    for reject_key in ("tradeErrorMessages", "errors", "errorMessages"):
        if confirmation.get(reject_key):
            return False
    # A recognized order-id key is the strongest signal; log which so
    # the real response shape becomes known from the trace.
    for id_key in (
        "orderIdentifier",
        "orderId",
        "financialInformationExchangeSystemOrderIdentifier",
    ):
        if confirmation.get(id_key):
            return True
    # No recognized id key, but a non-empty 2xx execute body with no
    # reject marker -> accept (avoids the double-buy false-negative).
    # Surface the keys so the real id field can be added above.
    print(
        "Chase execute 2xx with no recognized order-id key; "
        f"accepting as filled. confirmation keys: {list(confirmation)[:12]}",
    )
    return True


def _execute_single_order(ch_session: session.ChaseSession, all_accounts: ch_account.AllAccount, order_obj: StockOrder, ticker: str, account: str, price_type: order.PriceType, limit_price: float, key: str, loop: asyncio.AbstractEventLoop | None) -> None:  # noqa: PLR0917
    """Execute a single order for one account."""
    target_account_id = get_account_id(all_accounts.account_connectors, account)
    if not target_account_id:
        print_and_discord(f"{key} {account}: Unable to find account ID, skipping order.", loop)
        return

    # Symbol normalization at the boundary (defense-in-depth, same
    # spirit as the Fidelity Symbol-input guard): catches stray
    # whitespace / mixed case before Chase's API silently rejects
    # the order with a generic 4xx.
    ticker = (ticker or "").upper().strip()
    if not ticker:
        print_and_discord(
            f"{key} {account}: empty ticker after normalization, skipping.",
            loop,
        )
        return

    # C2 + C1-pre: account filter + ledger intent reservation.
    play = reserve_or_skip(
        broker_key="chase", account=account, ticker=ticker,
        order_obj=order_obj,
        display_label=f"{key} {account}", loop=loop,
    )
    if play is None:
        return

    if order_obj.get_dry():
        print_and_discord("Running in DRY mode. No transactions will be made.", loop)

    if order_obj.get_action().capitalize() == "Buy":
        order_type = order.OrderSide.BUY
    else:
        # Reset to market for selling
        price_type = order.PriceType.MARKET
        order_type = order.OrderSide.SELL

    chase_order = order.Order(ch_session)
    try:
        messages = chase_order.place_order(
            account_id=target_account_id,
            quantity=int(order_obj.get_amount()),
            price_type=price_type,
            symbol=ticker,
            duration=order.Duration.DAY,
            order_type=order_type,
            dry_run=order_obj.get_dry(),
            limit_price=limit_price,
        )
    except Exception as exc:
        complete_or_fail(
            play, order_obj=order_obj, success=False, detail=str(exc),
        )
        raise

    _process_order_messages(messages, order_obj, key, account, loop)
    # Chase's order_messages dict carries ORDER INVALID (any non-empty
    # value = failure) and either ORDER VALIDATION (dry run) or
    # ORDER CONFIRMATION (live) on success. Use those for the outcome
    # rather than re-parsing the printed text.
    invalid = _flatten_chase_error(messages.get("ORDER INVALID"))
    # Defense-in-depth: confirm Chase's response is for the security
    # we asked about. A mismatch makes ORDER CONFIRMATION irrelevant —
    # we treat the order as FAILED so the ledger doesn't claim
    # success for a wrong-ticker fill.
    mismatch = _verify_chase_response(
        messages, symbol=ticker, quantity=int(order_obj.get_amount()),
        action=str(order_type.value if hasattr(order_type, "value") else order_type),
    )
    if mismatch:
        invalid = mismatch
        print_and_discord(f"{key} {account}: {mismatch}", loop)
    success = not bool(invalid) and _order_succeeded(
        messages, dry=order_obj.get_dry(),
    )
    detail = invalid or ""
    complete_or_fail(play, order_obj=order_obj, success=success, detail=detail)


def _process_ticker_orders(chase_obj: Brokerage, all_accounts: ch_account.AllAccount, order_obj: StockOrder, ticker: str, loop: asyncio.AbstractEventLoop | None) -> session.ChaseSession | None:
    """Process orders for a single ticker across all accounts."""
    ch_session = None

    for key in chase_obj.get_account_numbers():
        price_type = order.PriceType.MARKET
        limit_price = 0.0

        ch_session = cast("session.ChaseSession", chase_obj.get_logged_in_objects(key))

        # Determine limit or market for buy orders.
        # H2 fix: try each account in turn until one returns a usable
        # quote. The original code always used account_ids[0]; if that
        # specific account is restricted from the ticker (very common
        # with the OTC tickers this tool targets), the quote came back
        # zero and every downstream account's limit price was wrong.
        if order_obj.get_action().capitalize() == "Buy":
            account_ids = list([] if all_accounts.account_connectors is None else all_accounts.account_connectors.keys())
            symbol_quote = None
            for acct_id in account_ids:
                try:
                    candidate = symbols.SymbolQuote(
                        account_id=acct_id,
                        session=ch_session,
                        symbol=ticker,
                    )
                except Exception as quote_exc:
                    print(f"Chase quote attempt failed on acct {acct_id}: {quote_exc}")
                    continue
                # A usable quote has a non-zero last trade price. Zero
                # means the account couldn't fetch one (restricted /
                # ticker unavailable here); keep trying.
                if getattr(candidate, "last_trade_price_amount", 0) > 0:
                    symbol_quote = candidate
                    break
            if symbol_quote is None:
                # All accounts failed -> degrade to MARKET so we don't
                # send a bogus $0 limit downstream.
                print_and_discord(
                    f"{key} {ticker}: no account produced a usable quote; "
                    "falling back to MARKET",
                    loop,
                )
                price_type, limit_price = order.PriceType.MARKET, 0.0
            else:
                price_type, limit_price = _calculate_limit_price(symbol_quote, order_obj.get_action())

        print_and_discord(
            f"{key} {order_obj.get_action()}ing {order_obj.get_amount()} {ticker} @ {price_type.value}",
            loop,
        )

        try:
            print(chase_obj.get_account_numbers())
            for account in chase_obj.get_account_numbers(key):
                _execute_single_order(ch_session, all_accounts, order_obj, ticker, account, price_type, limit_price, key, loop)
        except Exception as e:
            print_and_discord(f"{key} {account}: Error submitting order: {e}", loop)
            print(traceback.format_exc())
            continue

    return ch_session


def chase_transaction(chase_obj: Brokerage, all_accounts: ch_account.AllAccount, order_obj: StockOrder, loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Handle Chase API transactions."""
    print()
    print("==============================")
    print("Chase")
    print("==============================")
    print()

    ch_session: session.ChaseSession | None = None

    for ticker in order_obj.get_stocks():
        ch_session = _process_ticker_orders(chase_obj, all_accounts, order_obj, ticker, loop)

    if ch_session:
        print_and_discord("Closing Chase browser...", loop)
        ch_session.close_browser()

    print_and_discord("All Chase transactions complete", loop)
