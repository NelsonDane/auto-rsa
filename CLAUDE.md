# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

AutoRSA is a CLI tool and Discord bot that buys, sells, and checks holdings across ~16 brokerages through a single command. Each brokerage is reached via an official API, an unofficial third-party API, or browser automation (Selenium / Playwright / NoDriver) as a last resort.

The installable package is `auto_rsa_bot` (console script of the same name); the source lives under `src/`. `autoRSA.py` at the repo root is a deprecated shim that just forwards to the package.

## Commands

This project uses **uv**. Python 3.12+ is required.

```bash
uv sync --all-groups              # install deps (incl. dev group: ruff, ty)
git submodule update --init --recursive  # REQUIRED: vendored libs + ruff style config live in submodules

uv run ruff format --check        # formatting check (CI runs this)
uv run ruff check                 # lint (CI runs this)
uv run ty check                   # type check (CI runs this, against Python 3.12/3.13)

uv build                          # build wheel + sdist
uv run auto_rsa_bot --help        # smoke test (the only "test" in CI)

# Run a command locally (see Usage below):
uv run auto_rsa_bot buy 1 AAPL robinhood true   # dry buy of 1 AAPL in Robinhood
uv run auto_rsa_bot holdings all                 # holdings across all configured brokers
uv run auto_rsa_bot discord                      # run the Discord bot
```

There is **no unit test suite**. CI (`.github/workflows/`) only enforces ruff format, ruff check, `ty` type checking, and a `--help` smoke test on the built wheel/sdist. To run the workflows locally use [Act](https://github.com/nektos/act).

### Running on NixOS (this machine)

`uv`/`python`/`ruff`/`ty` are **not installed globally** here. Run `uv` on demand via nix, and prefix each session:

```bash
export NIX_CONFIG="experimental-features = nix-command flakes"
nix run nixpkgs#uv -- sync --all-groups              # one-time / after dep changes
nix run nixpkgs#uv -- run ruff format --check
nix run nixpkgs#uv -- run ruff check
nix run nixpkgs#uv -- run ty check --python-version 3.12
```

Always drive the checks through `uv run` (not `nix run nixpkgs#ruff`/`#ty` directly): nixpkgs ships **newer** ruff/ty than this project pins, and the newer versions report false failures (e.g. ruff rules `PLW0717`, `RUF069` don't exist in the pinned `0.13.3`; a raw `ty` run without the synced venv floods with `unresolved-import`). `uv run` uses the pinned tools with deps resolved — that matches CI.

**Requires `nix-ld`.** uv downloads a standalone CPython that NixOS can't execute out of the box (stub-ld error), which also blocks manylinux wheels. With `programs.nix-ld.enable = true;` in the NixOS config, `uv sync` and all checks work. As of last run, all three checks pass clean.

Ruff config lives in `pyproject.toml` but `extend`s `./styles/ruff.toml`, which is a git submodule — lint will fail if submodules aren't initialized. Vendored broker libraries (`src/vendors/robin_stocks`, `src/vendors/webull`) are also submodules and are excluded from lint/type-check.

## Architecture

**Entry flow:** `src/cli.py` (a Typer app that passes raw args through) → `src/auto_rsa.py:main()`. The first positional arg selects the mode:
- `docker` or `discord` → start the Discord bot (`docker` also sets `docker_mode=True`).
- anything else → parse a one-shot CLI command via `arg_parser()` and run it immediately.

**`arg_parser()` → `StockOrder`:** turns CLI/Discord args into a `StockOrder` (defined in `src/helper_api.py`). Two shapes:
- `holdings <brokers> [not <brokers>]`
- `[buy|sell] <amount> <ticker(s)> <brokers> [not <brokers>] [dry:true|false]`

Brokers accept comma-separated names/nicknames or the group keywords `all`, `day1`, `most`, `fast`. **Dry mode defaults to true** — a real transaction requires an explicit `false` as the final arg.

**`fun_run()` is the dispatcher.** It iterates the order's brokers and `match`es on `BrokerName` to call per-broker functions. Brokers follow one of two conventions:
1. **Three-function brokers** — `<broker>_init`, `<broker>_holdings`, `<broker>_transaction` (e.g. `robinhood`, `bbae`, `tastytrade`). `_init` returns a `Brokerage`; then holdings or transaction runs on the main thread.
2. **Single `<broker>_run` brokers** — `chase`, `fidelity`, `sofi`, `vanguard`, `wellsfargo`. These are the browser-automation brokers; they run inside a `ThreadHandler` (a thread wrapper that captures return value + exception) because their drivers need their own thread. `fun_run` folds the returned value into `total_value` **only if it's a `Brokerage` instance** (`isinstance(result, Brokerage)`) — `wellsfargo_run` returns its `Brokerage`; `chase_run`/`fidelity_run`/`sofi_run`/`vanguard_run` currently return `None`, so their totals are **not** counted in "Combined Total Value Across Brokers" (a pre-existing gap, only fixed for wellsfargo so far — same one-line return-the-Brokerage-object fix would close it for the others).

All per-broker modules live in `src/brokerages/`. When adding or changing a broker you must touch **both** the module and the `match` arms in `fun_run()` (init/holdings/transaction), plus register it in `src/brokers.py`.

**Broker registry — `src/brokers.py`:** the `BrokerName` StrEnum plus a frozen `BrokerInfo` dataclass per broker carrying `nicknames`, `day1`, and `fast` flags. `AllBrokersInfo` builds the lists behind the `all` / `day1` / `fast` / `most` keywords and resolves user input via `parse_input()`.

**`src/helper_api.py` — shared machinery:**
- `StockOrder` — holds action/amount/stocks/brokers/dry state and `order_validate(pre_login=...)`.
- `Brokerage` — per-broker session container: logged-in objects, account numbers, holdings, totals.
- `ThreadHandler` — runs a browser broker in a thread and surfaces its result/error to `fun_run`.
- `print_and_discord()` — the standard output path; prints to stdout AND, when a Discord bot/loop is passed, sends (chunked) embeds. Broker code should report through this, not bare `print`, so Discord output works.
- Selenium helpers (`get_selenium_driver`, `kill_all_selenium_drivers`, `type_slowly`, …).

**Credentials:** each broker reads its **own uppercase env var** from `.env` (e.g. `ROBINHOOD`, `CHASE`, `SCHWAB`). The value is comma-separated accounts, and each account is colon-separated fields (`user:pass:...`, broker-specific). A few brokers need extra vars (`SCHWAB_ACCOUNT_NUMBERS`, `VANGUARD_ACCOUNT_NUMBERS`, `PUBLIC_BROKER`). See `.env.example` for the full list. Discord bot vars: `DISCORD_TOKEN`, `DISCORD_CHANNEL`, optional `DISCORD_PREFIX` (default `!`) and `DISCORD_RSA_COMMAND` (default `rsa`).

**Notable env flags:** `DANGER_MODE=true` skips the interactive confirmation prompt before real orders. `HEADLESS` controls browser visibility for automation brokers.

**Discord bot** (built in `main()` when in bot mode) registers `!rsa <args>`, `!ping`, `!help`, `!version`, and `!restart`. It only listens on the configured channel. `restart` uses a special exit code so a Docker container restarts.

**Vendored `robin_stocks`:** loaded via an `importlib` hack near the top of `auto_rsa.py` that points `sys.modules["robin_stocks"]` at the inner folder of the submodule — a workaround until the upstream package is updated. Keep this in mind if imports of `robin_stocks` behave unexpectedly.

**Wells Fargo (`wellsfargo_api.py`) — zendriver + cookie trust, NOT Selenium.** WF aggressively blocks browser automation on fresh sessions: it returns a fake *"That combination doesn't match our records"* even for correct credentials. This is **device-trust**, not webdriver-flag detection (proven: zendriver with `navigator.webdriver=False` gets the same rejection as Selenium). The module works around it by:
- Driving Chrome with **zendriver** (a stealth `nodriver` fork; SoFi uses the same `nodriver` pattern) instead of Selenium. Declared as a **direct** pyproject dependency (pinned `>=0.15.4`) even though it also arrives transitively via `chaseinvest-api`, since `wellsfargo_api.py` imports it directly.
- Two cookie sources: an immutable **seed** (`creds/wellsfargo-cookies.json`, git-ignored) hand-exported once from a browser where WF login works (any OS/browser, e.g. Cookie-Editor JSON export), and a **rolling session** (`creds/wellsfargo-session.dat`, git-ignored) written via zendriver's `cookies.save()` after every successful login and preferred via `cookies.load()` on the next run. WF rotates its device-trust token on each login, so the rolling session — not the static seed — is what keeps logins working run over run. If the rolling session has gone stale, `_login` self-heals by clearing cookies and falling back to the seed once before raising a clear "re-export" error. The seed file is only strictly required to bootstrap the very first login; after that a valid session file alone is enough.
- Running as a `wellsfargo_run` + `ThreadHandler` broker on its own asyncio loop (`wf_loop`), like SoFi.

zendriver gotchas encoded in the module: `Browser.stop()` is a **coroutine** (must be awaited) and only SIGTERMs the main Chrome process — Chromium respawns helpers during graceful shutdown, so `_hard_stop_browser` SIGKILLs the captured process tree first (children before parent), then closes the websocket (calling `stop()` on a dead process hangs). Orphaned Chromium zombies are reaped by **`init: true`** (tini as PID 1) in `docker-compose.yml`. **Holdings and buy/sell both work**, confirmed against the live account (a real 1-share limit buy was placed and verified in WellsTrade's Orders tab).

**Buy/sell (`_place_one_order`, `_wellsfargo_transaction`) — WFA trade-UI quirks:**
- Most WFA trade-screen controls (`#trademenu`'s submenu links, `#BuySellBtn`, `#OrderTypeBtnText`, `#TIFBtn`, `#actionbtnContinue`, `.btn-wfa-submit`, `.btn-wfa-primary`, `#actionbtnCancel`) need a **JS click** (`_click_js`, `document.querySelector(...).click()`), not zendriver's real `.click()` — many exist in the DOM before their CSS-driven dropdown/animation makes them visibly positioned, and zendriver's real click needs a resolvable bounding box. Always `page.select(selector, timeout=...)` first to wait for the element to *exist*, then `_click_js` it — a plain `page.sleep(N)` before a JS click is not reliable, since settle time after an account switch or a real order submission genuinely varies.
- WFA's custom `<select>`-style dropdowns (Buy/Sell, Order Type, TIF) render as `<li><a data-val="...">text</a></li>` lists. Use `_click_exact_text(page, text)`, which queries only `a, button` (**not** `li`/`span`) for an exact, visible text match — including `li`/`span` in that query matches the non-interactive wrapper first (it comes before its child `<a>` in DOM order) and silently clicks nothing. zendriver's own `page.find(text)` is a fuzzy whole-page match and is *not* a safe substitute (e.g. `find("Day")` or `find("Limit")` can resolve to the wrong node).
- The account dropdown (`#dropdown2`/`dropdownlist2`) is matched by digits only (`mask.replace("*", "")`) — `_collect_accounts` must store a clean `***1234`-style mask. WF's `innerText` on the masked-number span **also includes a visually-hidden accessibility label** ("Account number ending in"); extract trailing digits via `re.sub(r"[^0-9]", "", tile["mask"])`, don't trust the raw text.
- After clicking Preview (`#actionbtnContinue`), the wizard needs a beat (`page.sleep(3)`) before it actually transitions — check too soon and you're still looking at the stale "Enter Order" step. WF renders both blocking `.alert-msg-summary` **"Error:"** banners (abort, cancel) and non-blocking **"Warning:"** ones (e.g. "limit price is on the wrong side of the market... may execute immediately" — safe to proceed) through the *same* element; only abort on `"error"` (case-insensitive prefix match), not on any banner presence.
- Real submit is `.btn-wfa-submit` (confirmed against the live "Preview & Submit" step-2 screen); it has no stable `id`. `#actionbtnCancel` only exists on step 1 (Enter Order) — step 2's back control is `#btnedit` ("EDIT"), not a cancel button, so the non-dry failure path's cancel-click only applies when still stuck on step 1.
- `wellsfargo_run`/`_wellsfargo_transaction` iterate **every** account mask under a login unconditionally (no per-account CLI targeting) — a buy/sell against a `$0` sub-account will legitimately fail with WF's own "insufficient funds" error; that's expected, not a bug.

**Cookie persistence (fixed).** Earlier zendriver 0.15.2 + Chromium 149 had a bug where Chromium dropped the cookie `sameParty` field and every cookie-*read* CDP path (`cookies.get_all`/`save`, `network.get_cookies`, `storage.get_cookies`) raised `KeyError('sameParty')` and hung. **Fixed upstream in zendriver 0.15.3** (`cdpdriver/zendriver#245`) — bumping the pin resolved it, confirmed via a live `get_all`/`save`/`load` round trip and an end-to-end container test (seed-only first login → session file written → seed removed → second login succeeds from the session file alone, with `browser.cookies.save()` wrapped in `contextlib.suppress` so a save failure — e.g. a host bind-mount permission mismatch — never fails an otherwise-successful login/holdings run). If `./creds` is a bind mount on a rootless-Docker host, the mount may need `chmod o+w` for the container's uid to write `wellsfargo-session.dat`.

## Deployment

The intended runtime is Docker. `entrypoint.sh` starts an Xvfb virtual framebuffer (browser-automation brokers need a display) and then runs `auto_rsa_bot docker`. `docker-compose.yml` wires the `.env` file and volumes.
