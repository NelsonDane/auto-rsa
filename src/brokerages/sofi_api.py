import asyncio
import datetime
import os
import pathlib
import shutil
import sys
import traceback
from time import sleep
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

import nodriver as uc
import pyotp
from curl_cffi import requests
from discord.ext.commands import Bot
from dotenv import load_dotenv
from nodriver.core.browser import Browser, tab

from src.helper_api import Brokerage, StockOrder, complete_or_fail, get_local_timezone, get_otp_from_discord, mask_string, print_all_holdings, print_and_discord, reserve_or_skip

load_dotenv()

COOKIES_PATH = "creds"
# Hard cap on every SoFi backend HTTP call (curl_cffi has no default
# timeout, so a slow/unresponsive endpoint would hang the run forever
# with no output — observed right after login on holdings fetch).
_HTTP_TIMEOUT = 30
# Get or create the event loop
try:
    sofi_loop = asyncio.get_event_loop()
except RuntimeError:
    sofi_loop = asyncio.new_event_loop()


def _create_creds_folder() -> None:
    """Create the 'creds' folder if it doesn't exist."""
    if not pathlib.Path(COOKIES_PATH).exists():
        pathlib.Path(COOKIES_PATH).mkdir(parents=True)


def _build_headers(csrf_token: str | None = None) -> dict[str, str]:
    """Build headers for HTTP requests."""
    headers = {
        "accept": "application/json",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "x-requested-with": "XMLHttpRequest",
    }
    if csrf_token is not None:
        headers["csrf-token"] = csrf_token
        headers["origin"] = "https://www.sofi.com"
        headers["referer"] = "https://www.sofi.com/"
        headers["sec-fetch-site"] = "same-origin"
        headers["sec-fetch-mode"] = "cors"
        headers["sec-fetch-dest"] = "empty"
    return headers


async def _save_cookies_to_pkl(browser: Browser, cookie_filename: str) -> None:
    try:
        await browser.cookies.save(cookie_filename)
    except Exception as e:
        print(f"Failed to save cookies: {e}")


async def _load_cookies_from_pkl(browser: Browser, page: tab.Tab, cookie_filename: str) -> bool:
    try:
        await browser.cookies.load(cookie_filename)
        await page.reload()
    except ValueError as e:
        print(f"Failed to load cookies: {e}")
    except FileNotFoundError:
        print("Cookie file does not exist.")
    else:
        return True
    return False


async def _sofi_error(error: str, page: tab.Tab | None = None, discord_loop: asyncio.AbstractEventLoop | None = None) -> None:
    if page is not None:
        try:
            timestamp = datetime.datetime.now(get_local_timezone()).strftime("%Y%m%d_%H%M%S")
            screenshot_name = f"SoFi-error-{timestamp}.png"
            await page.save_screenshot(filename=screenshot_name, full_page=True)
        except Exception as e:
            print(f"Failed to take screenshot: {e}")
    try:
        print_and_discord(f"Sofi error: {error}", discord_loop)
        print(f"SoFi Error: {traceback.format_exc()}")
    except Exception as e:
        print(f"Failed to log error: {e}")


async def get_current_url(page: tab.Tab, discord_loop: asyncio.AbstractEventLoop | None = None) -> str | None:
    """Get the current page URL by evaluating JavaScript.

    Resilient to nodriver's stale-document-node race: if SoFi is
    mid-redirect (e.g. sofi.com -> login page) when this is called,
    page.select("body") raises ProtocolException -32000 "Could not
    find node with given id" because nodriver's cached document
    refers to the PRE-redirect page. Retry the select up to 15 times
    (same pattern already used after the Log-In click below);
    nodriver re-fetches the doc on the next call so the next attempt
    succeeds.
    """
    await page.sleep(1)
    select_ok = False
    for attempt in range(15):
        try:
            await page.select("body")
            select_ok = True
            break
        except Exception as exc:
            if attempt == 0:
                # Log once so the diagnostic trace shows the race fired,
                # then suppress the rest of the retries to avoid spam.
                print(f"get_current_url: body select race; retrying ({exc})")
            await asyncio.sleep(1)
    if not select_ok:
        # 15 attempts at 1s each — the page is genuinely stuck.
        await _sofi_error(
            "get_current_url: body never settled after 15 attempts",
            page=page, discord_loop=discord_loop,
        )
        return None
    try:
        # Run JavaScript to get the current URL
        current_url = await page.evaluate("window.location.href")
    except Exception as e:
        await _sofi_error(f"Error fetching the current URL {e}", page=page, discord_loop=discord_loop)
        return None
    else:
        return str(current_url)


def _find_system_chrome() -> str | None:
    """Resolve the system Google Chrome path for nodriver, or None.

    nodriver's auto-detect can miss the right binary (or pick
    patchright's "Chrome for Testing"); passing an explicit path is the
    reliable fix. None -> let nodriver auto-detect (Linux/CI).
    """
    if sys.platform == "darwin":
        for app in (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ):
            if pathlib.Path(app).exists():
                return app
    for exe in ("google-chrome", "chrome", "chromium", "chromium-browser"):
        found = shutil.which(exe)
        if found:
            return found
    return None


def sofi_run(order_obj: StockOrder, command: tuple[str, str] | None = None, bot_obj: Bot | None = None, loop: asyncio.AbstractEventLoop | None = None) -> None:  # noqa: C901, PLR0912, PLR0915
    """Run the SoFi process.

    ``command`` is the legacy CLI ``(broker, "_holdings"|"_transaction")``
    tuple. The GUI engine dispatches via ThreadHandler without it, so
    when omitted the mode is derived from the order itself (matching how
    the other ThreadHandler brokers — Chase/Fidelity — work).
    """
    print("Initializing SoFi process...")
    load_dotenv()
    _create_creds_folder()
    browser = None

    if not os.getenv("SOFI"):
        return

    accounts = os.environ["SOFI"].strip().split(",")
    sofi_obj = Brokerage("SoFi")

    # Get headless flag
    headless = os.getenv("HEADLESS", "true").lower() == "true"

    # Set the functions to be run. Without an explicit CLI command,
    # derive holdings-vs-trade from the order (GUI/ThreadHandler path).
    if command is not None:
        _, second_command = command
    else:
        second_command = "_holdings" if order_obj.get_holdings() else "_transaction"

    cookie_filename = None
    try:
        for account in accounts:
            index = accounts.index(account) + 1
            name = f"SoFi {index}"
            cookie_filename = f"{COOKIES_PATH}/{name}.pkl"
            browser_args = [
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            ]
            # Use nodriver's native headless handling (a manual
            # --headless=new arg breaks its debug-socket connect) and an
            # explicit Chrome path so it doesn't fail to find/attach.
            start_kwargs: dict[str, object] = {
                "browser_args": browser_args,
                "headless": headless,
            }
            chrome_path = _find_system_chrome()
            if chrome_path:
                start_kwargs["browser_executable_path"] = chrome_path
            browser = sofi_loop.run_until_complete(uc.start(**start_kwargs))
            print(f"Logging into {name}...")
            init_result = sofi_init(account, name, cookie_filename, bot_obj, browser, loop, sofi_obj)
            sofi_loop.run_until_complete(browser.sleep(5))
            if init_result is None:
                # sofi_init returned None -> exception inside init; the
                # _sofi_error path already logged the cause. Don't pretend
                # we're logged in and don't fire holdings / transaction
                # against an unauthenticated session.
                print(f"SoFi {name}: init failed, skipping holdings/transaction.")
                continue
            print(f"Logged in to {name}!")
            if second_command == "_holdings":
                sofi_holdings(browser, name, sofi_obj, loop)
            else:
                sofi_transaction(browser, order_obj, loop)
            print(f"SoFi {name}: all done.")
    except Exception as e:
        sofi_loop.run_until_complete(_sofi_error(f"Error during SoFi init process: {e}", discord_loop=loop))
        return
    finally:
        # Cleanup must be bounded -- nodriver's cookies.save() calls
        # CDP Storage.getCookies internally, which was observed
        # hanging post-login (same bug we bypassed for the read
        # path). browser.stop() might also issue CDP calls during
        # teardown. A frozen cleanup is what kept the browser
        # window open and prevented the run from reporting
        # completion. Wrap both in asyncio.wait_for so a hang in
        # either step times out cleanly instead of freezing.
        if browser and cookie_filename:
            try:
                sofi_loop.run_until_complete(
                    asyncio.wait_for(
                        _save_cookies_to_pkl(browser, cookie_filename),
                        timeout=10,
                    ),
                )
            except TimeoutError:
                print("SoFi: cookies.save() timed out (CDP hang); skipping.")
            except Exception as e:
                print(f"SoFi: cookies.save() failed: {e}")
            # browser.stop() is synchronous in nodriver; if it ever
            # hangs we can't easily wait_for it, but it usually
            # completes instantly. Wrapped in try/except so any
            # teardown error doesn't mask the run's actual outcome.
            try:
                browser.stop()
                print("SoFi: browser closed.")
            except Exception as e:
                print(f"SoFi: browser.stop() failed: {e}")
    return


# SoFi init/login can wedge silently — nodriver's browser.get and
# page.get block forever on a Chrome that's stopped responding. Bound
# each navigation with a real timeout so a stuck session aborts the
# run with a clear "[sofi-init] nav timed out" message instead of
# freezing. Also surfaces per-step traces so we can pinpoint hangs.
_SOFI_NAV_TIMEOUT_S = 30


def _sofi_log(step: str, t0: float, extra: str = "") -> None:
    """Print a `[sofi-init] T+Xs <step> <extra>` diagnostic line."""
    dt = datetime.datetime.now(datetime.UTC).timestamp() - t0
    suffix = f" {extra}" if extra else ""
    print(f"[sofi-init] T+{dt:5.1f}s {step}{suffix}", flush=True)


async def _nav_with_timeout(
    coro_factory: "Callable[[], Awaitable[object]]", *, label: str, t0: float,
    timeout: float = _SOFI_NAV_TIMEOUT_S,  # noqa: ASYNC109
) -> object:
    """Await a navigation coroutine bounded by ``timeout`` seconds.

    Raises Exception on hang -- caller's existing try/except in
    sofi_init turns that into a clean _sofi_error line instead of
    a silent freeze.
    """
    _sofi_log(f"{label} ->", t0, f"timeout={timeout}s")
    try:
        result = await asyncio.wait_for(coro_factory(), timeout=timeout)
    except TimeoutError:
        _sofi_log(f"{label} TIMED OUT", t0)
        msg = f"SoFi nav '{label}' did not complete within {timeout}s"
        raise Exception(msg) from None
    _sofi_log(f"{label} <-", t0, "ok")
    return result


async def _soft_nav(
    coro_factory: "Callable[[], Awaitable[object]]", *, label: str, t0: float,
    timeout: float = 10,  # noqa: ASYNC109
) -> object | None:
    """Fire a navigation, tolerate non-settling, DON'T cancel mid-flight.

    SoFi's login + wealth-app pages are SPAs that keep WebSockets
    and polling open indefinitely, so nodriver's ``page.get`` /
    ``browser.get`` "page loaded" callback never fires even though
    the page rendered visually within a second or two.

    Two failure modes the strict ``_nav_with_timeout`` triggers
    when used on an SPA nav:

    1. The 60s+ wait burns budget pointlessly.
    2. ``asyncio.wait_for`` CANCELS the underlying coroutine on
       timeout. If the cancel arrives before nodriver has actually
       sent the ``Page.navigate`` CDP command (or while the CDP
       handler is still wiring up), the navigation never happens.
       Browser stays on the previous URL — observed in the
       operator's log as "stuck on sofi home page, multiple
       refreshes".

    Use ``asyncio.shield`` so the navigation coroutine survives our
    wait_for cancellation: the CDP command IS sent, the browser DOES
    navigate, and we just stop waiting for the "settled" notification
    that won't come. The caller MUST then verify by polling for an
    expected element with ``page.wait_for(selector=...)``.
    """
    _sofi_log(f"{label} (soft) ->", t0, f"timeout={timeout}s")
    nav = asyncio.ensure_future(coro_factory())
    try:
        result = await asyncio.wait_for(asyncio.shield(nav), timeout=timeout)
    except TimeoutError:
        _sofi_log(
            f"{label} (soft) did not settle in {timeout}s — continuing "
            "(nav still in flight via shield; caller will verify via "
            "the next element lookup)",
            t0,
        )
        return None
    else:
        _sofi_log(f"{label} (soft) <-", t0, "ok")
        return result


def sofi_init(  # noqa: PLR0917
    sofi_account: str,
    name: str,
    cookie_filename: str,
    bot_obj: Bot | None,
    browser: Browser,
    discord_loop: asyncio.AbstractEventLoop | None,
    sofi_obj: Brokerage,
) -> Brokerage | None:
    """Initialize the SoFi object."""
    page = None
    t0 = datetime.datetime.now(datetime.UTC).timestamp()
    _sofi_log("start", t0, f"name={name}")
    try:
        sleep(5)
        _sofi_log("post-sleep(5)", t0)
        account = sofi_account.split(":")

        # The page sometimes doesn't load until after retrying
        max_attempts = 5
        attempts = 0
        while attempts < max_attempts:
            page = sofi_loop.run_until_complete(
                _nav_with_timeout(
                    lambda: browser.get("https://www.sofi.com/"),
                    label=f"warmup nav attempt {attempts + 1}", t0=t0,
                ),
            )
            sofi_loop.run_until_complete(page)  # Wait for events to be processed
            current_url = sofi_loop.run_until_complete(get_current_url(page, discord_loop))
            _sofi_log(f"warmup attempt {attempts + 1} url", t0, repr(current_url))
            if current_url == "https://www.sofi.com/":
                break

            attempts += 1

        # Load cookies
        if page:
            sofi_loop.run_until_complete(page)  # Wait for events to be processed
        page = sofi_loop.run_until_complete(
            _nav_with_timeout(
                lambda: browser.get("https://www.sofi.com"),
                label="sofi.com second nav", t0=t0,
            ),
        )
        sofi_loop.run_until_complete(browser.sleep(5))
        _sofi_log("loading cookies", t0, cookie_filename)
        cookies_loaded = sofi_loop.run_until_complete(
            _load_cookies_from_pkl(browser, page, cookie_filename),
        )
        _sofi_log("cookies result", t0, f"loaded={cookies_loaded}")

        if cookies_loaded:
            sofi_loop.run_until_complete(
                _nav_with_timeout(
                    lambda: page.get("https://www.sofi.com/wealth/app/"),
                    label="wealth/app/ nav (cookies path)", t0=t0,
                ),
            )
            sofi_loop.run_until_complete(browser.sleep(5))
            sofi_loop.run_until_complete(page.select("body"))
            current_url = sofi_loop.run_until_complete(
                get_current_url(page, discord_loop),
            )
            _sofi_log("post-cookies url", t0, repr(current_url))

            if current_url and "overview" in current_url:
                sofi_loop.run_until_complete(
                    _save_cookies_to_pkl(browser, cookie_filename),
                )
                _sofi_log("done via cookies", t0)
                return sofi_obj

        _sofi_log("starting fresh login", t0)
        # Proceed with login if cookies are invalid or expired
        sofi_loop.run_until_complete(
            _sofi_login_and_account(browser, page, account, name, bot_obj, discord_loop, init_t0=t0),
        )
        sofi_obj.set_logged_in_object(name, browser)
        _sofi_log("init complete", t0)
    except Exception as e:
        _sofi_log("EXCEPTION", t0, repr(e))
        sofi_loop.run_until_complete(
            _sofi_error(
                f"Error during SoFi init process: {e}",
                page=page,
                discord_loop=discord_loop,
            ),
        )
        return None
    return sofi_obj


async def _js_navigate(
    page: tab.Tab, url: str, *, label: str, t0: float,
) -> None:
    """Trigger navigation via ``window.location.href`` from inside the page.

    nodriver's ``page.get`` / ``browser.get`` await a CDP "page
    settled" event that never fires on SoFi's SPA. Wrapping
    them in ``asyncio.shield`` was supposed to keep the nav
    alive after our wait_for timeout, but operator observation
    confirmed otherwise: post-shield, the URL was still the
    PRIOR page (sofi.com homepage, not /wealth/app). The nav
    command was never sent.

    JS-driven navigation via ``Runtime.evaluate`` is a different
    CDP code path that completes as soon as Chrome accepts the
    assignment — typically in milliseconds — regardless of
    whether the destination page ever finishes loading.
    """
    _sofi_log(f"{label} (JS nav) -> {url}", t0)
    try:
        await asyncio.wait_for(
            page.evaluate(f"window.location.href = {url!r}"),
            timeout=10,
        )
        _sofi_log(f"{label} (JS nav) cmd sent", t0)
    except (TimeoutError, asyncio.CancelledError) as exc:
        _sofi_log(f"{label} (JS nav) timed out: {exc!r}", t0)
    except Exception as exc:
        _sofi_log(f"{label} (JS nav) threw: {exc!r}", t0)


async def _wait_for_login_form(
    page: tab.Tab, name: str, *, t0: float,
    discord_loop: asyncio.AbstractEventLoop | None,
) -> object:
    """Poll for the SoFi login form with diagnostic + one reload retry.

    SoFi's Auth0-hosted login page is an SPA whose JS rendering
    occasionally stalls (sometimes the form is there in 200ms,
    sometimes it doesn't show in 30s — observed across runs with
    no code change). When the first 15s budget elapses without
    finding ``input[id=username]``, this helper:

    1. Logs the current URL (so we can tell whether we're on the
       login page at all, or stuck on a homepage redirect / CAPTCHA).
    2. Saves a screenshot named ``SoFi-form-missing-<ts>.png``
       in the working directory so the operator can see the page
       state at the failure point.
    3. Reloads the page once and waits another 30s.

    Only re-raises with a clearer message after the reload retry
    also fails -- so a transient SPA stall has a real chance to
    recover instead of killing the run.
    """
    _sofi_log("login: waiting for username input (polling 15s)", t0)
    try:
        return await page.wait_for(
            selector="input[id=username]", timeout=15,
        )
    except Exception:
        _sofi_log("login: form not found in 15s; diagnosing", t0)

    # Capture diagnostic state.
    try:
        curr_url = await asyncio.wait_for(
            get_current_url(page, discord_loop), timeout=5,
        )
    except Exception:
        curr_url = "<get_current_url failed>"
    _sofi_log("login: current url at form-missing", t0, repr(curr_url))
    try:
        ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d_%H%M%S")
        shot = f"SoFi-form-missing-{ts}.png"
        await asyncio.wait_for(
            page.save_screenshot(filename=shot, full_page=True),
            timeout=10,
        )
        _sofi_log(f"login: screenshot saved {shot}", t0)
    except Exception as exc:
        _sofi_log(f"login: screenshot failed: {exc!r}", t0)

    # Retry once: if we ended up on the homepage (operator's
    # screenshot showed this), JS-navigate to /login/ explicitly
    # rather than reloading the wrong page.
    if "sofi.com/" in str(curr_url) and "login" not in str(curr_url):
        _sofi_log("login: stuck on homepage; re-navigating via JS to /login/", t0)
        await _js_navigate(
            page, "https://www.sofi.com/login/",
            label="login retry JS nav", t0=t0,
        )
    else:
        _sofi_log("login: reloading current page and waiting up to 30s", t0)
        try:
            await asyncio.wait_for(page.reload(), timeout=10)
        except Exception as exc:
            _sofi_log(f"login: reload threw {exc!r}; continuing anyway", t0)
    await asyncio.sleep(5)
    try:
        return await page.wait_for(
            selector="input[id=username]",
            timeout=_SOFI_NAV_TIMEOUT_S,
        )
    except Exception as exc:
        msg = (
            f"Login form never rendered for SoFi {name} "
            f"(input[id=username] not found after reload retry; "
            f"current url={curr_url!r}): {exc}"
        )
        raise Exception(msg) from None


async def _sofi_login_and_account(browser: Browser, page: tab.Tab, account: list[str], name: str, bot_obj: Bot | None = None, discord_loop: asyncio.AbstractEventLoop | None = None, init_t0: float | None = None) -> None:  # noqa: C901, PLR0915, PLR0917
    """Drive the SoFi login form with timed step traces.

    ``init_t0`` shares the [sofi-init] trace timeline so log lines
    from sofi_init and this function are plotted against the same
    start moment.
    """
    t0 = init_t0 if init_t0 is not None else datetime.datetime.now(datetime.UTC).timestamp()
    try:
        _sofi_log("login: pre-sleep(5)", t0)
        await asyncio.sleep(5)
        _sofi_log("login: post-sleep, navigating sofi.com", t0)
        page = await _nav_with_timeout(
            lambda: browser.get("https://www.sofi.com"),
            label="login sofi.com nav", t0=t0,
        )
        if not page:
            msg = f"Failed to load SoFi login page for {name}"
            raise Exception(msg)

        _sofi_log("login: navigating to /login/ directly", t0)
        # Operator observation: page.get('/wealth/app') was leaving
        # us stuck on www.sofi.com homepage even with asyncio.shield.
        # The /wealth/app URL is intended for authenticated users
        # and bounces through Auth0 redirects that nodriver's
        # event-driven nav can't always resolve.
        #
        # /login/ is the canonical, browser-loadable login URL --
        # static enough that JS-driven navigation reliably lands on
        # the form. JS nav (window.location.href = ...) doesn't
        # depend on the page-settled callback that's been failing.
        await _js_navigate(
            page, "https://www.sofi.com/login/",
            label="login nav", t0=t0,
        )
        await asyncio.sleep(3)
        username_input = await _wait_for_login_form(
            page, name, t0=t0, discord_loop=discord_loop,
        )
        await username_input.send_keys(account[0])
        _sofi_log("login: typed username", t0)

        # SoFi's Auth0 flow is multi-step: page 1 has just the
        # username field + a Continue button; clicking it advances
        # to page 2 which has the password field. If we skip the
        # advance, page.wait_for(input[type=password]) either
        # returns nothing (and we abort) OR matches an off-screen
        # input that takes the typed text but goes nowhere
        # visible -- the operator observed "username and password
        # entered together in username field" with the URL still
        # showing /u/login after click, confirming the password
        # never actually landed in a password field. Look for
        # Continue / Next / Submit by text; click if present;
        # if not, assume the form is single-step.
        advanced = False
        for label_text in ("Continue", "Next", "Submit"):
            try:
                advance_button = await asyncio.wait_for(
                    page.find(label_text, best_match=True),
                    timeout=3,
                )
            except (Exception, TimeoutError):
                advance_button = None
            if advance_button:
                _sofi_log(
                    f"login: clicked '{label_text}' (multi-step flow)",
                    t0,
                )
                try:
                    await advance_button.click()
                    await asyncio.sleep(2)
                    advanced = True
                    break
                except Exception as exc:
                    _sofi_log(
                        f"login: '{label_text}' click failed: {exc!r}",
                        t0,
                    )
                    continue
        if not advanced:
            _sofi_log("login: no advance button found; single-step form", t0)

        try:
            password_input = await page.wait_for(
                selector="input[type=password]",
                timeout=_SOFI_NAV_TIMEOUT_S,
            )
        except Exception as exc:
            msg = (
                f"Unable to locate the password input field for "
                f"SoFi {name}: {exc}"
            )
            raise Exception(msg) from None
        await password_input.send_keys(account[1])
        _sofi_log("login: typed password", t0)

        login_button = await asyncio.wait_for(
            page.find("Log In", best_match=True), timeout=_SOFI_NAV_TIMEOUT_S,
        )
        if not login_button:
            msg = f"Unable to locate the login button for {name}"
            raise Exception(msg)
        await login_button.click()
        _sofi_log("login: clicked Log In", t0)

        # Clicking "Log In" navigates, so nodriver's cached document
        # node goes stale ("Could not find node with given id"). Poll
        # for the new page rather than a single brittle select() that
        # races the navigation and aborts the whole login.
        await asyncio.sleep(3)
        for attempt in range(15):
            try:
                await page.select("body")
                _sofi_log(f"login: post-click body found on attempt {attempt + 1}", t0)
                break
            except Exception:  # stale node mid-navigation; retry
                await asyncio.sleep(1)

        current_url = await get_current_url(page, discord_loop)
        _sofi_log("login: post-click url", t0, repr(current_url))
        if current_url is not None and "overview" not in current_url:
            _sofi_log("login: 2FA branch", t0)
            await _handle_2fa(
                page, account, name, bot_obj, discord_loop,
                t0=t0, url_hint=current_url,
            )
    except Exception as e:
        _sofi_log("login EXCEPTION", t0, repr(e))
        await _sofi_error(
            f"Error logging into account {name}: {e}",
            page=page,
            discord_loop=discord_loop,
        )
        # Re-raise so sofi_init's outer try/except sets init_result
        # to None and sofi_run skips the holdings/transaction step
        # instead of pretending login succeeded.
        raise


async def _in_page_fetch(  # noqa: PLR0911
    browser: Browser, url: str, *, label: str, t0: float,
    timeout: float = _SOFI_NAV_TIMEOUT_S,  # noqa: ASYNC109
    method: str = "GET",
    body: dict | None = None,
) -> dict | list | None:
    """Run ``fetch(url)`` inside the page context and return its JSON.

    Why not requests + extracted cookies: nodriver's
    ``browser.cookies.get_all()`` (CDP ``Storage.getCookies``) was
    observed hanging post-login on the operator's box, blowing past
    a 30s timeout. Even when extraction works, ``document.cookie``
    only returns non-HttpOnly cookies — SoFi's session token is
    HttpOnly, so direct requests calls would 401 without it.

    Running ``fetch()`` in the page context sidesteps both problems:
    the browser supplies the session jar (including HttpOnly) AND
    automatically handles CSRF tokens. ``credentials: 'include'``
    is sufficient for both reads (GET) and writes (POST with body).

    Returns the parsed JSON body on 2xx, or ``None`` on any failure
    (logged via ``_sofi_log``). Caller decides whether to raise.

    Implementation detail: the JS wrapper returns
    ``JSON.stringify({ok, data})`` rather than the object itself.
    Reason: nodriver's ``Runtime.evaluate`` object-marshalling
    strips the outer envelope when the resolved promise value is
    a complex object — operator log Dec 2025 showed our
    ``{ok:true, data:[...]}`` wrapper coming back as the raw
    list. JSON-string + Python-side parse is unambiguous.
    """
    import json as _json  # noqa: PLC0415

    _sofi_log(
        f"{label}: in-page fetch {method} {url}",
        t0, f"timeout={timeout}s",
    )
    tabs = list(getattr(browser, "tabs", []) or [])
    if not tabs:
        _sofi_log(f"{label}: no tabs available; aborting fetch", t0)
        return None
    page = tabs[-1]

    body_js = _json.dumps(body) if body is not None else "null"
    js = (
        "(async () => {"
        f"  const init = {{"
        f"    method: {method!r},"
        "    credentials: 'include',"
        "    headers: {"
        "      'accept': 'application/json',"
        "      'content-type': 'application/json',"
        "      'x-requested-with': 'XMLHttpRequest'"
        "    }"
        "  };"
        f"  const body = {body_js};"
        "  if (body !== null) init.body = JSON.stringify(body);"
        f"  const r = await fetch({url!r}, init);"
        "  if (!r.ok) {"
        "    let bodyText = ''; try { bodyText = await r.text(); } catch (e) {}"
        "    return JSON.stringify({ok: false, status: r.status, body: bodyText.slice(0, 500)});"
        "  }"
        "  let data; try { data = await r.json(); } catch (e) { data = null; }"
        "  return JSON.stringify({ok: true, data: data});"
        "})()"
    )
    try:
        raw = await asyncio.wait_for(
            page.evaluate(js, await_promise=True),
            timeout=timeout,
        )
    except (TimeoutError, asyncio.CancelledError) as exc:
        _sofi_log(f"{label}: in-page fetch TIMED OUT", t0, repr(exc))
        return None
    except Exception as exc:
        _sofi_log(f"{label}: in-page fetch EXCEPTION", t0, repr(exc))
        return None

    if isinstance(raw, str):
        try:
            parsed = _json.loads(raw)
        except ValueError as exc:
            _sofi_log(
                f"{label}: returned non-JSON string", t0,
                f"{exc!r} sample={raw[:200]!r}",
            )
            return None
    elif isinstance(raw, dict):
        parsed = raw
    else:
        _sofi_log(
            f"{label}: unexpected fetch envelope shape", t0,
            f"type={type(raw).__name__} sample={str(raw)[:200]!r}",
        )
        return None

    if not isinstance(parsed, dict) or "ok" not in parsed:
        _sofi_log(f"{label}: envelope missing 'ok' key", t0, repr(parsed)[:200])
        return None
    if not parsed.get("ok"):
        _sofi_log(
            f"{label}: SoFi rejected fetch",
            t0,
            f"status={parsed.get('status')} body={str(parsed.get('body'))[:200]!r}",
        )
        return None
    return parsed.get("data")


async def _sofi_account_info(browser: Browser, discord_loop: asyncio.AbstractEventLoop | None = None) -> dict[str, dict[str, float]] | None:
    """Fetch the post-login SoFi account list via in-page fetch().

    Uses ``_in_page_fetch`` instead of extracting cookies +
    curl_cffi.requests — both because nodriver's cookie
    extraction was observed hanging on this operator's setup,
    and because SoFi's HttpOnly session cookie wouldn't be
    visible to document.cookie anyway.
    """
    t0 = datetime.datetime.now(datetime.UTC).timestamp()
    _sofi_log("holdings: enter", t0)
    try:
        await browser.sleep(1)
        _sofi_log("holdings: pre-overview nav", t0)
        await _soft_nav(
            lambda: browser.get("https://www.sofi.com/wealth/app/overview"),
            label="wealth/app/overview nav", t0=t0, timeout=10,
        )
        _sofi_log("holdings: post-overview nav, sleeping 3s", t0)
        await browser.sleep(3)

        accounts_data = await _in_page_fetch(
            browser,
            "https://www.sofi.com/wealth/backend/v1/json/accounts",
            label="holdings: /json/accounts", t0=t0,
        )
        if accounts_data is None:
            msg = (
                "SoFi /json/accounts fetch failed (see preceding "
                "[sofi-holdings] line for HTTP status / body)."
            )
            raise Exception(msg)
        if not isinstance(accounts_data, list):
            msg = f"SoFi /json/accounts returned unexpected shape: {type(accounts_data).__name__}"
            raise Exception(msg)  # noqa: TRY004

        account_dict: dict[str, dict[str, float]] = {}
        for account in accounts_data:
            account_number = account["apexAccountId"]
            account_id = account["id"]
            account_type = account["type"]["description"]
            current_value = account["totalEquityValue"]

            account_dict[account_number] = {
                "type": account_type,
                "balance": float(current_value),
                "id": account_id,
            }
        _sofi_log("holdings: parsed accounts", t0, f"n={len(account_dict)}")
    except Exception as e:
        _sofi_log("holdings: EXCEPTION", t0, repr(e))
        await _sofi_error(
            f"Error fetching SoFi account information: {e}",
            discord_loop=discord_loop,
        )
        return None
    else:
        return account_dict


def sofi_holdings(browser: Browser, name: str, sofi_obj: Brokerage, discord_loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Retrieve and display all SoFi account holdings."""
    t0 = datetime.datetime.now(datetime.UTC).timestamp()
    _sofi_log(f"holdings: sofi_holdings start name={name}", t0)
    account_dict = sofi_loop.run_until_complete(_sofi_account_info(browser, discord_loop))
    if not account_dict:
        msg = f"Failed to retrieve account info for {name}"
        raise Exception(msg)
    _sofi_log(f"holdings: got {len(account_dict)} accounts", t0)

    for i, (acct, account_info) in enumerate(account_dict.items(), start=1):
        _sofi_log(f"holdings: account {i}/{len(account_dict)} {mask_string(acct)}", t0)
        real_account_number = acct
        sofi_obj.set_account_number(name, real_account_number)
        sofi_obj.set_account_totals(name, real_account_number, account_info["balance"])

        account_id = str(account_info.get("id"))
        try:
            holdings_data = sofi_loop.run_until_complete(
                _in_page_fetch(
                    browser,
                    f"https://www.sofi.com/wealth/backend/api/v3/account/{account_id}/holdings?accountDataType=INTERNAL",
                    label=f"holdings: account {mask_string(account_id)}", t0=t0,
                ),
            )
        except Exception as e:
            _sofi_log(f"holdings: fetch FAILED for {mask_string(account_id)}", t0, repr(e))
            sofi_loop.run_until_complete(
                _sofi_error(
                    f"Error fetching holdings for SOFI account {mask_string(account_id)}: {e}",
                    discord_loop=discord_loop,
                ),
            )
            continue
        if not isinstance(holdings_data, dict):
            _sofi_log(
                f"holdings: account {mask_string(account_id)} fetch returned no data",
                t0,
            )
            continue

        holdings = [
            {
                "company_name": str(h.get("symbol", "N/A")) or "N/A",
                "shares": h.get("shares", "N/A"),
                "price": h.get("price", "N/A"),
            }
            for h in holdings_data.get("holdings", [])
        ]
        _sofi_log(f"holdings: got {len(holdings)} positions for {mask_string(account_id)}", t0)

        for holding in holdings:
            company_name = str(holding.get("company_name", "N/A"))
            if company_name == "|CASH|":
                continue

            shares = holding.get("shares", "N/A")
            price = holding.get("price", "N/A")
            sofi_obj.set_holdings(
                name,
                real_account_number,
                company_name,
                shares,
                price,
            )

    # Log info after holdings are processed
    _sofi_log("holdings: all done", t0)
    print(f"All holdings processed for {name}.")
    print_all_holdings(sofi_obj, discord_loop)


def _get_holdings_formatted(account_id: str, cookies: dict[str, str]) -> list[dict[str, float | str]]:
    holdings_url = f"https://www.sofi.com/wealth/backend/api/v3/account/{account_id}/holdings?accountDataType=INTERNAL"
    response = requests.get(
        holdings_url,
        impersonate="chrome", timeout=_HTTP_TIMEOUT,
        headers=_build_headers(),
        cookies=cookies,
    )

    if not response.ok:
        msg = f"Failed to fetch holdings, status code: {response.status_code}"
        raise Exception(msg)

    holdings_data = response.json()

    formatted_holdings = []

    for holding in holdings_data.get("holdings", []):
        company_name = str(holding.get("symbol", "N/A"))
        shares = holding.get("shares", "N/A")
        price = holding.get("price", "N/A")

        formatted_holdings.append(
            {
                "company_name": company_name or "N/A",
                "shares": float(shares) if shares is not None else "N/A",
                "price": float(price) if price is not None else "N/A",
            },
        )

    return formatted_holdings


def _get_2fa_code(secret: str) -> str:
    totp = pyotp.TOTP(secret)
    return totp.now()


async def _handle_2fa(page: tab.Tab, account: list[str], name: str, bot_obj: Bot | None, discord_loop: asyncio.AbstractEventLoop | None, t0: float | None = None, url_hint: str | None = None) -> None:  # noqa: C901, PLR0912, PLR0915, PLR0917
    """Handle SoFi's 2FA prompt using URL-based path selection.

    SoFi shows ONE of two challenge URLs at this step:

    * ``mfa-sms-challenge`` — SoFi already sent a text. The form
      input only accepts the SMS code, NOT a TOTP code, even when
      the user has authenticator-app 2FA configured. (Confirmed
      by operator log Dec 2025: TOTP entered into the SMS form
      was silently rejected — the page stayed on the challenge
      URL and the run printed 'init complete' without ever
      authenticating.)
    * ``mfa-otp-challenge`` / ``mfa-app-challenge`` — authenticator
      app step. Form accepts TOTP from a configured secret, or a
      manually-typed code.

    So path selection MUST be URL-driven:

    +-----------------------+----------------+------------------+
    | URL                   | secret set?    | Code source      |
    +-----------------------+----------------+------------------+
    | mfa-sms-challenge     | yes OR no      | prompt operator  |
    |                       |                | (typed-in SMS)   |
    +-----------------------+----------------+------------------+
    | mfa-otp-challenge     | yes            | TOTP from secret |
    +-----------------------+----------------+------------------+
    | mfa-otp-challenge     | no             | prompt operator  |
    |                       |                | (typed-in TOTP)  |
    +-----------------------+----------------+------------------+
    | (none of the above)   | any            | page-text SMS    |
    |                       |                | detection then   |
    |                       |                | prompt           |
    +-----------------------+----------------+------------------+

    Post-submit: poll the URL for up to 20s. If still on a
    challenge URL, raise — operator typed a wrong code or SoFi
    rejected it, and the caller's try/except sets init_result=None
    so the run doesn't pretend it logged in.
    """
    t0 = t0 if t0 is not None else datetime.datetime.now(datetime.UTC).timestamp()
    _sofi_log("2fa: enter", t0, f"url={url_hint!r}")
    try:
        secret = account[2] if len(account) > 2 else None  # noqa: PLR2004
        if isinstance(secret, str) and (secret.lower() == "none" or secret.lower() == "false"):
            secret = None

        url_lower = (url_hint or "").lower()
        is_sms_url = "mfa-sms-challenge" in url_lower
        is_otp_url = (
            "mfa-otp-challenge" in url_lower
            or "mfa-app-challenge" in url_lower
        )

        # Determine the code SOURCE.
        if is_sms_url:
            _sofi_log("2fa: SMS path (URL match)", t0)
            if secret is not None:
                _sofi_log(
                    "2fa: NOTE TOTP secret is set but URL is SMS-only; "
                    "SoFi will reject TOTP here. Prompting for the "
                    "texted code instead.", t0,
                )
            code_source = "sms"
        elif is_otp_url:
            _sofi_log("2fa: authenticator path (URL match)", t0)
            code_source = "totp" if secret is not None else "prompt"
        else:
            # URL is something else (older flow or new variant) —
            # fall back to the historical behavior: secret-first.
            _sofi_log("2fa: URL not recognized, falling back", t0)
            code_source = "totp" if secret is not None else "sms"

        # Tick the "Remember this browser" checkbox if SoFi shows
        # one — same on both challenge pages.
        try:
            remember = await asyncio.wait_for(
                page.select("input[id=rememberBrowser]"),
                timeout=5,
            )
            if remember:
                await remember.click()
                _sofi_log("2fa: rememberBrowser ticked", t0)
        except TimeoutError:
            _sofi_log("2fa: no rememberBrowser checkbox; continuing", t0)

        # Locate the code input. Same id on both challenge pages.
        code_input = await page.select("input[id=code]")
        if not code_input:
            msg = (
                f"Unable to locate 2FA input field for SoFi {name}. "
                f"URL was {url_hint!r}; SoFi DOM may have changed."
            )
            raise Exception(msg)

        # Get the code from the appropriate source.
        if code_source == "totp":
            two_fa_code = _get_2fa_code(secret)
            _sofi_log("2fa: generated TOTP code from secret", t0)
        elif bot_obj is not None and discord_loop is not None:
            _sofi_log("2fa: requesting code via Discord webhook", t0)
            two_fa_code = asyncio.run_coroutine_threadsafe(
                get_otp_from_discord(bot_obj, name, timeout=300, loop=discord_loop),
                discord_loop,
            ).result()
            if two_fa_code is None:
                msg = f"SoFi {name}: code not received in time."
                raise Exception(msg)
        else:
            prompt_kind = "SMS code (check your phone)" if code_source == "sms" else "authenticator app code"
            _sofi_log(f"2fa: prompting operator for {prompt_kind}", t0)
            two_fa_code = input(  # noqa: ASYNC250
                f"SoFi {name} 2FA — {prompt_kind}: ",
            )

        await code_input.send_keys(two_fa_code)
        _sofi_log("2fa: code typed into form", t0)
        verify_button = await page.find("Verify Code")
        if verify_button:
            await verify_button.click()
            _sofi_log("2fa: Verify Code clicked", t0)
        else:
            _sofi_log("2fa: WARNING Verify Code button not found", t0)

        # Post-submit verification: poll the URL for up to 20s. If
        # we don't leave a challenge URL, the code was wrong /
        # rejected — raise so caller knows login failed instead of
        # silently returning.
        for attempt in range(20):
            await asyncio.sleep(1)
            try:
                post_url = await get_current_url(page, discord_loop)
            except Exception:
                post_url = None
            if post_url is None:
                continue
            post_lower = post_url.lower()
            still_challenge = (
                "mfa-sms-challenge" in post_lower
                or "mfa-otp-challenge" in post_lower
                or "mfa-app-challenge" in post_lower
            )
            if not still_challenge:
                _sofi_log(
                    f"2fa: post-submit url after {attempt + 1}s",
                    t0, repr(post_url),
                )
                return
        msg = (
            f"SoFi {name}: 2FA code rejected — page is still on a "
            f"challenge URL 20s after Verify Code click. Source was "
            f"{code_source!r}; secret_configured={secret is not None}. "
            "Re-check the code (TOTP windows are 30s) and that the "
            "right method matches SoFi's prompt URL."
        )
        raise Exception(msg)

    except Exception as e:
        _sofi_log("2fa: EXCEPTION", t0, repr(e))
        await _sofi_error(
            f"Error during 2FA handling for {name}: {e}",
            page=page,
            discord_loop=discord_loop,
        )
        raise


def sofi_transaction(browser: Browser, order_boj: StockOrder, discord_loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Handle SoFi API transactions."""
    dry_mode = order_boj.get_dry()
    for stock in order_boj.get_stocks():
        if order_boj.get_action() == "buy":
            sofi_loop.run_until_complete(
                _sofi_buy(
                    browser, stock, order_boj.get_amount(), discord_loop,
                    order_obj=order_boj, dry_mode=dry_mode,
                ),
            )
        elif order_boj.get_action() == "sell":
            sofi_loop.run_until_complete(
                _sofi_sell(
                    browser, stock, order_boj.get_amount(), discord_loop,
                    order_obj=order_boj, dry_mode=dry_mode,
                ),
            )
        else:
            print(f"Unknown action: {order_boj.get_action()}")


async def _sofi_buy(browser: Browser, symbol: str, quantity: float, discord_loop: asyncio.AbstractEventLoop | None = None, *, order_obj: StockOrder | None = None, dry_mode: bool = False) -> None:  # noqa: C901, PLR0912
    page = None
    try:
        # Step 1: Navigate to the stock page so the browser's session
        # context is loaded. Cookies / CSRF are NOT extracted -- the
        # subsequent _in_page_fetch calls reuse the browser's existing
        # session jar (HttpOnly + CSRF) automatically via
        # credentials:'include'.
        stock_url = f"https://www.sofi.com/wealth/app/stock/{symbol}"
        await _soft_nav(
            lambda: browser.get(stock_url),
            label=f"buy stock-page nav {symbol}",
            t0=datetime.datetime.now(datetime.UTC).timestamp(),
            timeout=10,
        )

        # Step 2: Get the stock price
        stock_price = await _fetch_stock_price(browser, symbol)
        if stock_price is None:
            msg = f"Failed to retrieve stock price for {symbol}"
            raise Exception(msg)

        limit_price = stock_price

        # Step 3: Fetch all funded accounts and their buying power
        accounts = await _fetch_funded_accounts(browser)
        if not accounts:
            msg = "Failed to retrieve funded accounts or none available."
            raise Exception(msg)

        # Step 4: Loop through all accounts to check buying power and place the limit order
        for account in accounts:
            account_id = account["accountId"]
            buying_power = account["accountBuyingPower"]
            account_name = account.get("accountType")

            # C2 + C1-pre: account filter + ledger intent reservation.
            # order_obj is required for proper ledger semantics; if a
            # legacy caller passes None we degrade gracefully (no
            # reservation, no record — the audit script already flags
            # the call site).
            play = None
            if order_obj is not None:
                play = reserve_or_skip(
                    broker_key="sofi", account=account_id, ticker=symbol,
                    order_obj=order_obj,
                    display_label=f"SoFi {mask_string(account_id)}",
                    loop=discord_loop,
                )
                if play is None:
                    continue

            total_price = limit_price * quantity
            if total_price <= buying_power:
                if dry_mode:
                    # Dry mode: Log what would have been done
                    print_and_discord(
                        f"[DRY MODE] Would place limit order for {symbol} in account {account_name} with limit price: {limit_price}",
                        discord_loop,
                    )
                    if play is not None and order_obj is not None:
                        complete_or_fail(
                            play, order_obj=order_obj,
                            success=True, detail="dry run",
                        )
                    continue

                if quantity < 1:
                    result = await _place_fractional_order(
                        browser, symbol, quantity, account_id,
                        order_type="BUY", discord_loop=discord_loop,
                    )
                else:
                    result = await _place_order(
                        browser, symbol, quantity, limit_price, account_id,
                        order_type="BUY", discord_loop=discord_loop,
                    )
                if result and result["header"] == "Your order is placed.":  # Success
                    print_and_discord(
                        f"Successfully bought {quantity} of {symbol} in account {mask_string(account_id)}",
                        discord_loop,
                    )
                    if play is not None and order_obj is not None:
                        complete_or_fail(
                            play, order_obj=order_obj, success=True,
                            detail="bought",
                        )
                elif play is not None and order_obj is not None:
                    complete_or_fail(
                        play, order_obj=order_obj, success=False,
                        detail=str(result),
                    )
            else:
                print_and_discord(
                    f"Insufficient buying power in {account_name}. Needed: {total_price}, Available: {buying_power}",
                    discord_loop,
                )
                if play is not None and order_obj is not None:
                    complete_or_fail(
                        play, order_obj=order_obj, success=False,
                        detail=f"insufficient buying power "
                        f"(need {total_price}, have {buying_power})",
                    )
    except Exception as e:
        await _sofi_error(
            f"Error during buy transaction for {symbol}: {e}",
            page=page,
            discord_loop=discord_loop,
        )


async def _sofi_sell(browser: Browser, symbol: str, quantity: float, discord_loop: asyncio.AbstractEventLoop | None = None, *, order_obj: StockOrder | None = None, dry_mode: bool = False) -> None:  # noqa: C901, PLR0912
    t0 = datetime.datetime.now(datetime.UTC).timestamp()
    try:
        # Fetch holdings for the specific symbol via in-page fetch
        # (no cookie / CSRF extraction; the browser session is used
        # via credentials:'include').
        holdings_data = await _in_page_fetch(
            browser,
            f"https://www.sofi.com/wealth/backend/api/v3/customer/holdings/symbol/{symbol}",
            label=f"sell holdings-lookup {symbol}", t0=t0,
        )
        if not isinstance(holdings_data, dict):
            msg = f"Failed to fetch holdings for {symbol} (see preceding log)."
            raise Exception(msg)  # noqa: TRY004

        account_holding_infos = holdings_data.get("accountHoldingInfos", [])
        if not account_holding_infos:
            msg = f"No holdings found for symbol {symbol}. Cannot proceed with the sell order."
            raise Exception(msg)

        total_available_shares = sum(info["salableQuantity"] for info in account_holding_infos)
        if total_available_shares < quantity:
            msg = f"Not enough shares to sell. Available: {total_available_shares}, Requested: {quantity}"
            raise Exception(msg)

        stock_price = await _fetch_stock_price(browser, symbol)
        if stock_price is None:
            msg = f"Failed to retrieve stock price for {symbol}"
            raise Exception(msg)

        limit_price = round(stock_price - 0.01, 2)

        # Loop through all accounts holding the stock
        for account in account_holding_infos:
            account_id = account["accountId"]
            available_shares = account["salableQuantity"]

            # Skip accounts where available shares are less than the quantity to sell
            if available_shares < quantity:
                print_and_discord(
                    f"Not enough shares to sell {quantity} of {symbol} in account {mask_string(account_id)}. Only {available_shares} available.",
                    discord_loop,
                )
                continue  # Move to the next account

            # C2 + C1-pre: account filter + ledger intent reservation.
            play = None
            if order_obj is not None:
                play = reserve_or_skip(
                    broker_key="sofi", account=account_id, ticker=symbol,
                    order_obj=order_obj,
                    display_label=f"SoFi {mask_string(account_id)}",
                    loop=discord_loop,
                )
                if play is None:
                    continue

            if dry_mode:
                # Dry mode: Log what would have been done
                print_and_discord(
                    f"[DRY MODE] Would place sell order for {quantity} shares of {symbol} in account {mask_string(account_id)}",
                    discord_loop,
                )
                if play is not None and order_obj is not None:
                    complete_or_fail(
                        play, order_obj=order_obj,
                        success=True, detail="dry run",
                    )
                continue

            if quantity < 1:
                result = await _place_fractional_order(
                    browser, symbol, quantity, account_id,
                    order_type="SELL", discord_loop=discord_loop,
                )
            else:
                result = await _place_order(
                    browser, symbol, quantity, limit_price, account_id,
                    order_type="SELL", discord_loop=discord_loop,
                )
            if result and result["header"] == "Your order is placed.":  # Success
                print_and_discord(
                    f"Successfully sold {quantity} of {symbol} in account {mask_string(account_id)}",
                    discord_loop,
                )
                if play is not None and order_obj is not None:
                    complete_or_fail(
                        play, order_obj=order_obj, success=True, detail="sold",
                    )
            elif play is not None and order_obj is not None:
                complete_or_fail(
                    play, order_obj=order_obj, success=False,
                    detail=str(result),
                )
    except Exception as e:
        await _sofi_error(
            f"Error during sell transaction for {symbol}: {e}",
            discord_loop=discord_loop,
        )


async def _fetch_funded_accounts(browser: Browser) -> list | None:
    """Fetch SoFi's funded brokerage accounts via in-page fetch."""
    t0 = datetime.datetime.now(datetime.UTC).timestamp()
    result = await _in_page_fetch(
        browser,
        "https://www.sofi.com/wealth/backend/api/v1/user/funded-brokerage-accounts",
        label="funded-accounts", t0=t0,
    )
    if result is None:
        return None
    # SoFi returns a list directly; tolerate either shape.
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return result.get("accounts", result)
    return None


async def _fetch_stock_price(browser: Browser, symbol: str) -> float | None:
    """Fetch the current price for a symbol via in-page fetch."""
    t0 = datetime.datetime.now(datetime.UTC).timestamp()
    try:
        url = f"https://www.sofi.com/wealth/backend/api/v1/tearsheet/quote?symbol={symbol}&productSubtype=BROKERAGE"
        data = await _in_page_fetch(
            browser, url, label=f"quote-{symbol}", t0=t0,
        )
        if isinstance(data, dict):
            price = data.get("price")
            if price:
                # Round the price to the nearest second decimal place
                return round(float(price), 2)
        print(f"Failed to fetch stock price for {symbol}.")
    except Exception as e:
        await _sofi_error(f"Error fetching stock price for {symbol}: {e}")
    return None


async def _place_order(  # noqa: PLR0917
    browser: Browser,
    symbol: str,
    quantity: float,
    limit_price: float,
    account_id: str,
    order_type: str,
    discord_loop: asyncio.AbstractEventLoop | None = None,
) -> dict | None:
    """Place a whole-share LIMIT order via in-page fetch."""
    t0 = datetime.datetime.now(datetime.UTC).timestamp()
    try:
        payload = {
            "operation": order_type,
            "quantity": str(quantity),
            "time": "DAY",
            "type": "LIMIT",
            "limitPrice": limit_price,
            "symbol": symbol,
            "accountId": account_id,
            "tradingSession": "CORE_HOURS",
        }
        result = await _in_page_fetch(
            browser,
            "https://www.sofi.com/wealth/backend/api/v1/trade/order",
            label=f"order-{order_type}-{symbol}", t0=t0,
            method="POST", body=payload,
        )
        if result is not None and isinstance(result, dict):
            return result
        # _in_page_fetch already logged the SoFi error body. Re-derive
        # the "cannot be traded" surface for the caller's existing
        # error-handling branch.
        print(f"Failed to place order for {symbol} (see [sofi-holdings] log).")
    except Exception as e:
        await _sofi_error(
            f"Error placing order for {symbol}: {e}",
            discord_loop=discord_loop,
        )
    return None


async def _place_fractional_order(  # noqa: PLR0917
    browser: Browser,
    symbol: str,
    quantity: float,
    account_id: str,
    order_type: str,
    discord_loop: asyncio.AbstractEventLoop | None = None,
) -> dict | None:
    """Place a fractional MARKET order (sub-1-share) via in-page fetch."""
    t0 = datetime.datetime.now(datetime.UTC).timestamp()
    try:
        stock_price = await _fetch_stock_price(browser, symbol)
        if stock_price is None:
            msg = f"Failed to retrieve stock price for {symbol}"
            raise Exception(msg)

        cash_amount = round(stock_price * quantity, 2)
        payload = {
            "operation": order_type,
            "cashAmount": cash_amount,
            "quantity": quantity,
            "symbol": symbol,
            "accountId": account_id,
            "time": "DAY",
            "type": "MARKET",
            "tradingSession": "CORE_HOURS",
            "sellAll": False,
        }
        result = await _in_page_fetch(
            browser,
            "https://www.sofi.com/wealth/backend/api/v1/trade/order-fractional",
            label=f"order-frac-{order_type}-{symbol}", t0=t0,
            method="POST", body=payload,
        )
        if result is not None and isinstance(result, dict):
            return result
        print(f"Failed to place fractional order for {symbol} (see [sofi-holdings] log).")
    except Exception as e:
        await _sofi_error(
            f"Error placing fractional order for {symbol}: {e}",
            discord_loop=discord_loop,
        )
    return None
