"""Wells Fargo automation via zendriver.

Wells Fargo aggressively blocks browser automation on fresh sessions (it
returns a fake "combination doesn't match" even for correct credentials).
To get past that we inject the user's real device-trust cookies, exported
once from their own browser to ``creds/wellsfargo-cookies.json`` (any OS /
browser via a Cookie-Editor style JSON export). With those cookies WF trusts
the session, accepts the login, and skips 2FA.

Re-export the cookies whenever WF stops trusting them (they expire).
"""

import asyncio
import contextlib
import datetime
import json
import os
import re
import signal
import traceback
from pathlib import Path
from typing import cast

import zendriver as zd
from discord.ext.commands import Bot
from dotenv import load_dotenv
from zendriver import cdp
from zendriver.core.browser import Browser
from zendriver.core.tab import Tab

from src.helper_api import Brokerage, StockOrder, get_local_timezone, print_all_holdings, print_and_discord

LOGIN_URL = "https://connect.secure.wellsfargo.com/auth/login/present"
# The user's hand-exported Cookie-Editor JSON (device-trust seed, immutable fallback).
COOKIE_FILE = os.environ.get("WELLSFARGO_COOKIES", "creds/wellsfargo-cookies.json")
# zendriver's native cookie dump, refreshed after every successful login. WF
# rotates its device-trust token on login, so this rolling session (not the
# static seed above) is what keeps logins working run over run.
SESSION_FILE = os.environ.get("WELLSFARGO_SESSION", "creds/wellsfargo-session.dat")
_CHROMIUM_PATH = "/usr/bin/chromium"
CHROMIUM_EXE = _CHROMIUM_PATH if Path(_CHROMIUM_PATH).exists() else None

# Event loop for the (async) zendriver calls, run from the ThreadHandler
# worker thread -- mirrors the SoFi module's pattern (a bare new_event_loop
# trips asyncio_atexit into a recursion at interpreter shutdown).
try:
    wf_loop = asyncio.get_event_loop()
except RuntimeError:
    wf_loop = asyncio.new_event_loop()


def _same_site(value: str | None) -> "cdp.network.CookieSameSite | None":
    if not value:
        return None
    return {
        "strict": cdp.network.CookieSameSite.STRICT,
        "lax": cdp.network.CookieSameSite.LAX,
        "no_restriction": cdp.network.CookieSameSite.NONE,
        "none": cdp.network.CookieSameSite.NONE,
    }.get(value.lower())


def _load_cookie_params(path: str) -> list["cdp.network.CookieParam"]:
    """Parse a Cookie-Editor style JSON export into CDP cookie params."""
    with Path(path).open(encoding="utf-8") as f:
        raw = json.load(f)
    items = raw["cookies"] if isinstance(raw, dict) and "cookies" in raw else raw
    params = []
    for c in items:
        exp = c.get("expirationDate")
        params.append(
            cdp.network.CookieParam(
                name=c["name"],
                value=c["value"],
                domain=c.get("domain"),
                path=c.get("path", "/"),
                secure=c.get("secure"),
                http_only=c.get("httpOnly"),
                same_site=_same_site(c.get("sameSite")),
                expires=cdp.network.TimeSinceEpoch(exp) if exp else None,
            ),
        )
    return params


def _descendant_pids(root: int) -> list[int]:
    """Collect a pid and all of its descendants (Linux /proc walk)."""
    if not Path("/proc").is_dir():
        return [root]
    children: dict[int, list[int]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        with contextlib.suppress(OSError, ValueError):
            status = (entry / "status").read_text()
            ppid = next(int(line.split()[1]) for line in status.splitlines() if line.startswith("PPid:"))
            children.setdefault(ppid, []).append(int(entry.name))
    tree, stack = [], [root]
    while stack:
        pid = stack.pop()
        tree.append(pid)
        stack.extend(children.get(pid, []))
    return tree


async def _hard_stop_browser(browser: Browser) -> None:
    """Kill the browser's whole process tree, then close the connection.

    zendriver's ``stop()`` only SIGTERMs the main process, and Chromium
    respawns helper processes during graceful shutdown -- so we SIGKILL the
    captured tree first (children before parent) to avoid orphans.
    """
    proc = getattr(browser, "_process", None)
    pid = getattr(proc, "pid", None)
    pids = _descendant_pids(pid) if pid else []
    for p in reversed(pids):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(p, signal.SIGKILL)
    # Don't call browser.stop(): with the process already dead it hangs waiting
    # on a CDP close response. Just close the websocket connection instead.
    conn = getattr(browser, "connection", None)
    if conn is not None:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(conn.aclose(), timeout=5)


async def _wf_screenshot(page: Tab, tag: str) -> None:
    with contextlib.suppress(Exception):
        stamp = datetime.datetime.now(get_local_timezone())
        await page.save_screenshot(f"wells-fargo-{tag}-{stamp}.png")


async def _start_browser(*, docker_mode: bool) -> Browser:
    browser_args = ["--disable-gpu"]
    if docker_mode:
        browser_args += ["--no-sandbox", "--disable-dev-shm-usage"]
    return await zd.start(
        headless=True,
        sandbox=not docker_mode,
        browser_args=browser_args,
        browser_executable_path=CHROMIUM_EXE,
    )


async def _attempt_login(browser: Browser, account: list[str]) -> tuple[Tab, str]:
    """Navigate to WF and submit credentials; return (page, status).

    status is "ok", "mismatch" (untrusted/bad creds), "2fa" (trust lost), or
    "stuck" (still on the login page). Assumes cookies are already loaded.
    """
    page = await browser.get(LOGIN_URL)
    await page.sleep(6)
    url = await page.evaluate("document.location.href")
    if isinstance(url, str) and "/auth/login" not in url:
        # A live session cookie carried us straight to the dashboard.
        return page, "ok"

    username = await page.select("#j_username", timeout=20)
    await username.send_keys(account[0])
    password = await page.select("#j_password", timeout=20)
    await password.send_keys(account[1])
    await page.sleep(1)
    login_button = await page.select(".Button__modern___cqCp7", timeout=20)
    await login_button.click()
    await page.sleep(12)

    url = await page.evaluate("document.location.href")
    html = await page.get_content()
    if "match our records" in html:
        return page, "mismatch"
    if "modalContent" in html or "Enter the code" in html:
        return page, "2fa"
    if isinstance(url, str) and "/auth/login" in url:
        return page, "stuck"
    return page, "ok"


async def _login(
    browser: Browser,
    account: list[str],
    name: str,
    *,
    used_session: bool,
    has_seed: bool,
) -> Tab:
    """Log in and return the dashboard tab.

    Prefers the rolling session (``SESSION_FILE``, WF's current device-trust
    token, refreshed on every successful login) over the immutable seed
    (``COOKIE_FILE``, the user's hand-exported cookies). If the rolling
    session has gone stale -- WF rotates the token on login -- self-heal by
    falling back to the seed once before giving up (when one was exported).
    """
    if used_session:
        await browser.cookies.load(SESSION_FILE)
    else:
        await browser.cookies.set_all(_load_cookie_params(COOKIE_FILE))
    page, status = await _attempt_login(browser, account)

    if status != "ok" and used_session and has_seed:
        await browser.cookies.clear()
        await browser.cookies.set_all(_load_cookie_params(COOKIE_FILE))
        page, status = await _attempt_login(browser, account)

    if status == "ok":
        with contextlib.suppress(Exception):
            await browser.cookies.save(SESSION_FILE)
        return page

    await _wf_screenshot(page, "error")
    reasons = {
        "mismatch": f"WF rejected the login (device-trust cookies expired). Re-export {COOKIE_FILE}.",
        "2fa": f"WF asked for 2FA (device trust lost). Re-export {COOKIE_FILE} from a session where the device is remembered.",
        "stuck": "WF login did not complete (still on the login page).",
    }
    msg = f"{name}: {reasons.get(status, 'WF login failed.')}"
    raise Exception(msg)


async def _collect_accounts(page: Tab, name: str, wf_obj: Brokerage) -> None:
    """Read the WELLSTRADE account tiles (masked number + balance) into wf_obj."""
    await page.sleep(3)
    tiles = cast(
        "list[dict[str, str]]",
        await page.evaluate(
            """
        (() => {
          const out = [];
          document.querySelectorAll('li[data-testid^="WELLSTRADE"]').forEach((t) => {
            const num = t.querySelector('[data-testid$="-masked-number"]');
            const bal = t.querySelector('[data-testid$="-balance"]');
            if (num && bal) out.push({mask: num.innerText, balance: bal.innerText});
          });
          return out;
        })()
        """,
            return_by_value=True,
        ),
    )
    if not tiles:
        await _wf_screenshot(page, "no-accounts")
        print(f"{name}: no WELLSTRADE brokerage accounts found on the dashboard.")
        return
    for tile in tiles:
        # innerText also picks up the visually-hidden "Account number ending in"
        # accessibility label; keep only the trailing digits.
        digits = re.sub(r"[^0-9]", "", tile["mask"])
        mask = f"***{digits}"
        balance = float(tile["balance"].replace("$", "").replace(",", "").strip())
        wf_obj.set_account_number(name, mask)
        wf_obj.set_account_totals(name, mask, balance)


def wellsfargo_run(
    order_obj: StockOrder,
    bot_obj: Bot | None = None,  # noqa: ARG001  (kept for the ThreadHandler interface; 2FA is cookie-bypassed)
    loop: asyncio.AbstractEventLoop | None = None,
    *,
    docker_mode: bool = False,
) -> Brokerage | None:
    """Entry point for Wells Fargo (holdings and, later, transactions).

    Returns the populated ``Brokerage`` so ``fun_run`` can fold its account
    totals into the combined-total-across-brokers figure (the ThreadHandler
    brokers don't share state with the dispatcher any other way).
    """
    load_dotenv()
    if not os.getenv("WELLSFARGO"):
        print("WELLSFARGO environment variable not found.")
        return None
    if not Path(SESSION_FILE).exists() and not Path(COOKIE_FILE).exists():
        print_and_discord(
            f"Wells Fargo: neither {SESSION_FILE} nor {COOKIE_FILE} found. Export your WF cookies to the latter first (see the module docstring).",
            loop,
        )
        return None

    accounts = os.environ["WELLSFARGO"].strip().split(",")
    wf_obj = Brokerage("WELLSFARGO")

    for wells_account in accounts:
        index = accounts.index(wells_account) + 1
        name = f"WELLSFARGO {index}"
        account = wells_account.split(":")
        browser = None
        try:
            print_and_discord("Logging into WELLS FARGO...", loop)
            browser = wf_loop.run_until_complete(_start_browser(docker_mode=docker_mode))
            used_session = Path(SESSION_FILE).exists()
            has_seed = Path(COOKIE_FILE).exists()
            page = wf_loop.run_until_complete(
                _login(browser, account, name, used_session=used_session, has_seed=has_seed),
            )
            wf_obj.set_logged_in_object(name, browser)
            wf_loop.run_until_complete(_collect_accounts(page, name, wf_obj))
            if not order_obj.get_holdings():
                wf_loop.run_until_complete(_wellsfargo_transaction(order_obj, name, wf_obj, page, loop))
        except Exception as e:
            print_and_discord(f"Error with {name}: {e}", loop)
            traceback.print_exc()
        finally:
            if browser is not None:
                with contextlib.suppress(Exception):
                    wf_loop.run_until_complete(_hard_stop_browser(browser))

    if order_obj.get_holdings():
        print_all_holdings(wf_obj, loop)
    return wf_obj


async def _click_js(page: Tab, selector: str) -> None:
    """Click via JS: the WFA trade UI has visibility quirks that break a real click."""
    await page.evaluate(f"document.querySelector({selector!r}).click()")


async def _click_exact_text(page: Tab, text: str) -> bool:
    """Click the first visible interactive element with exact matching text (Selenium LINK_TEXT equivalent).

    Safer than zendriver's ``page.find()``, which does a fuzzy whole-page
    text search and can resolve to the wrong node when the target word (e.g.
    "Day", "Limit", "Market") also appears elsewhere on the page. Restricted
    to ``a``/``button`` (not their ``li``/``span`` wrappers): the WFA custom
    dropdowns put the actual click handler on the anchor, and querying the
    wrapping ``<li>`` too matches it first in DOM order -- clicking an inert
    ancestor that silently does nothing.
    """
    return bool(
        await page.evaluate(
            f"""
        (() => {{
            const target = {text!r};
            const nodes = document.querySelectorAll('a, button');
            for (const n of nodes) {{
                if (n.textContent.trim() === target && n.offsetParent !== null) {{
                    n.click();
                    return true;
                }}
            }}
            return false;
        }})()
        """,
            return_by_value=True,
        ),
    )


async def _goto_trade_stocks(page: Tab) -> None:
    """Navigate Brokerage -> Trade -> Trade Stocks from the account dashboard."""
    brokerage = await page.select("#BROKERAGE_LINK7P", timeout=20)
    await brokerage.click()
    await page.sleep(2)
    trade_menu = await page.select("#trademenu", timeout=20)
    await trade_menu.click()
    await page.sleep(1)
    await page.select("#linktradestocks", timeout=20)  # wait for it to exist
    await _click_js(page, "#linktradestocks")
    await page.sleep(2)
    await _wf_screenshot(page, "trade-landing")


async def _dismiss_continue_if_present(page: Tab) -> None:
    """Best-effort dismissal of the WFA 'clear ticket' confirmation prompt.

    ``#btn-continue`` can exist in the DOM (hidden, inert) even when no
    prompt is showing, so a real ``.click()`` may fail to resolve a visible
    position -- that's fine, it means there was nothing to dismiss.
    """
    with contextlib.suppress(Exception):
        btn = await page.select("#btn-continue", timeout=3)
        await btn.click()


async def _reset_trade_screen(page: Tab) -> None:
    """Re-open the trade-stocks screen after a failed/previewed order left it unusable."""
    trade_menu = await page.select("#trademenu", timeout=20)
    await trade_menu.click()
    await page.sleep(1)
    await page.select("#linktradestocks", timeout=20)  # wait for it to exist
    await _click_js(page, "#linktradestocks")
    await _dismiss_continue_if_present(page)
    await page.sleep(1)


async def _select_trade_account(page: Tab, mask: str) -> bool:
    """Open the account dropdown and pick the entry matching ``mask``. Returns success."""
    await page.select("#dropdown2", timeout=20)  # wait for the ticket form to (re)render
    await _click_js(page, "#dropdown2")
    await page.sleep(1)
    needle = mask.replace("*", "")
    found = await page.evaluate(
        f"""
        (() => {{
            var items = document.getElementById('dropdownlist2').getElementsByTagName('li');
            for (var i = 0; i < items.length; i++) {{
                if (items[i].innerText.includes({needle!r})) {{
                    items[i].click();
                    return true;
                }}
            }}
            return false;
        }})()
        """,
        return_by_value=True,
    )
    await page.sleep(2)
    await _dismiss_continue_if_present(page)
    await _wf_screenshot(page, f"account-selected-{mask.replace('*', '')}")
    return bool(found)


async def _place_one_order(  # noqa: C901, PLR0911, PLR0915
    page: Tab,
    order_obj: StockOrder,
    stock: str,
    *,
    name: str,
    mask: str,
    loop: asyncio.AbstractEventLoop | None,
) -> bool:
    """Fill out and submit (or dry-preview) a single buy/sell ticket. Returns whether it failed."""
    action = order_obj.get_action().lower()
    await page.select("#BuySellBtn", timeout=20)  # wait for the ticket form to (re)render
    await _click_js(page, "#BuySellBtn")
    if action not in {"buy", "sell"}:
        print_and_discord(f"{name} {mask}: no buy or sell set for {stock}", loop)
        return True
    if not await _click_exact_text(page, "Buy" if action == "buy" else "Sell"):
        print_and_discord(f"{name} {mask}: could not find the Buy/Sell toggle for {stock}", loop)
        return True

    await page.select("#actionbtnContinue", timeout=20)
    await page.sleep(2)
    ticker_box = await page.select("#Symbol", timeout=20)
    await ticker_box.send_keys(stock)
    await ticker_box.send_keys(zd.SpecialKeys.ENTER)

    await page.evaluate(f"document.querySelector('#OrderQuantity').value = {int(order_obj.get_amount())}")

    await page.select(".qeval", timeout=20)
    price_text = cast("str", await page.evaluate("document.querySelector('.qeval').innerText"))
    price = float(price_text)
    price_cutoff = 2.0
    if action == "buy" and price < price_cutoff:
        price_type, price = "Limit", price + 0.01
    elif action == "sell" and price < price_cutoff:
        price_type, price = "Limit", price - 0.01
    else:
        price_type = "Market"

    await _wf_screenshot(page, f"ticket-filled-{stock}")

    await _click_js(page, "#OrderTypeBtnText")
    if not await _click_exact_text(page, price_type):
        print_and_discord(f"{name} {mask}: could not select order type {price_type} for {stock}", loop)
        return True
    if price_type == "Limit":
        price_box = await page.select("#Price", timeout=20)
        await price_box.send_keys(str(round(price, 2)))
        await price_box.send_keys(zd.SpecialKeys.ENTER)
        await _click_js(page, "#TIFBtn")
        await page.sleep(1)
        if not await _click_exact_text(page, "Day"):
            print_and_discord(f"{name} {mask}: could not select Day TIF for {stock}", loop)
            return True

    await _click_js(page, "#actionbtnContinue")
    await page.sleep(3)  # let the wizard actually transition before inspecting it
    await _wf_screenshot(page, f"preview-{stock}")

    alert_text = cast(
        "str | None",
        await page.evaluate(
            "(() => { const e = document.querySelector('.alert-msg-summary'); if (!e) return null; const p = e.querySelector('p'); return (p ?? e).innerText; })()",
        ),
    )
    # WF shows both blocking "Error:" banners and non-blocking "Warning:" ones
    # (e.g. "limit price is on the wrong side of the market... to continue... click
    # submit") through the same element -- only the former should abort the order.
    if alert_text and alert_text.strip().lower().startswith("error"):
        print_and_discord(
            f"{name} {mask}: {order_obj.get_action()} {order_obj.get_amount()} shares of {stock}. Preview failed: {alert_text}",
            loop,
        )
        with contextlib.suppress(Exception):
            await _click_js(page, "#actionbtnCancel")
            await _dismiss_continue_if_present(page)
        return True

    if not order_obj.get_dry():
        try:
            await page.select(".btn-wfa-submit", timeout=10)
        except TimeoutError:
            error_text = await page.evaluate("document.querySelector('.alert-msg-summary p')?.innerText ?? 'unknown error'")
            print_and_discord(
                f"{name} {mask}: {order_obj.get_action()} {order_obj.get_amount()} shares of {stock}. FAILED! \n{error_text}",
                loop,
            )
            with contextlib.suppress(Exception):
                await _click_js(page, "#actionbtnCancel")
                await _dismiss_continue_if_present(page)
            return True
        await _click_js(page, ".btn-wfa-submit")
        print_and_discord(
            f"{name} {mask}: {order_obj.get_action()} {order_obj.get_amount()} shares of {stock}",
            loop,
        )
        with contextlib.suppress(Exception):
            await _click_js(page, ".btn-wfa-primary")
        return False

    print_and_discord(
        f"DRY: {name} account {mask}: {order_obj.get_action()} {order_obj.get_amount()} shares of {stock}",
        loop,
    )
    return True


async def _wellsfargo_transaction(
    order_obj: StockOrder,
    name: str,
    wf_obj: Brokerage,
    page: Tab,
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    """Handle Wells Fargo buy/sell orders across all accounts under this login."""
    account_masks = wf_obj.get_account_numbers(name)
    if not account_masks:
        print_and_discord(f"{name}: no accounts found, skipping transactions.", loop)
        return

    try:
        await _goto_trade_stocks(page)
    except TimeoutError:
        print_and_discord(f"{name}: could not reach the trade screen.", loop)
        return

    order_failed = False
    for mask in account_masks:
        if order_failed and order_obj.get_dry():
            await _reset_trade_screen(page)
        try:
            if not await _select_trade_account(page, mask):
                print_and_discord(f"{name} {mask}: could not select this account for trading.", loop)
                continue
        except TimeoutError:
            print_and_discord(f"{name} {mask}: could not open the account selector.", loop)
            continue
        # Freshly (re)selected -- clear any carry-over from a prior account so the
        # stock loop below doesn't redundantly reset+reselect on its first pass.
        order_failed = False

        for stock in order_obj.get_stocks():
            if order_failed:
                # The account selection persists across a trade-screen reset
                # (same underlying WF session) -- only re-navigate, don't reselect.
                await _reset_trade_screen(page)
            try:
                order_failed = await _place_one_order(page, order_obj, stock, name=name, mask=mask, loop=loop)
            except TimeoutError:
                print_and_discord(f"{name} {mask}: trade UI timed out placing {stock}.", loop)
                order_failed = True
