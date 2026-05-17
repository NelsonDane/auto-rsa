# Local Web GUI

A local browser GUI to manage broker logins and run trades/balance pulls
without the Discord bot. Credentials are stored in an encrypted vault
(unlocked with a master password); no `.env` file is required.

## Setup

From the repository folder:

```bash
# 1. Get the vendored sub-projects (robin_stocks, webull, styles)
git submodule update --init --recursive

# 2. Install Python dependencies (includes Streamlit)
uv sync

# 3. One-time: install the browser Playwright drives.
#    REQUIRED for Fidelity and Schwab (both use Playwright/Firefox).
uv run playwright install firefox
#    Or install all browsers (larger, fully covers every browser broker):
#    uv run playwright install
```

## Run

Easiest — use the launcher (it syncs deps and starts the app):

- **Windows:** double-click **`start-gui.cmd`** in the repo folder.
- **macOS / Linux:** run **`./start-gui.sh`** from the repo folder.

Or run it manually:

```bash
uv run streamlit run src/gui/app.py
# or:
uv run auto_rsa_gui
```

The app opens in your browser at `http://localhost:8501`. Keep the
terminal open while using it; `Ctrl+C` stops the app.

## First use

1. Sidebar: set a master password and click **Create vault** (later
   launches: enter the password and **Unlock**).
2. **Status** tab → **Run engine import check** to confirm the GUI is
   wired to the trading engine.
3. **Credentials** tab → fill in and **Save** each broker's login.
4. **Balances** tab → pull holdings (safe, read-only). **Trade** tab →
   place orders (dry-run is ON by default; turn it off for live orders).

A persistent panel above the tabs shows live status output and any 2FA /
OTP / CAPTCHA prompt. When a broker needs a code, type it there and
click **Submit** — the page does not auto-refresh while a prompt is open.

## Supported brokers

Chase, Robinhood, Wells Fargo, Fennel, Fidelity, DSPAC, BBAE, Schwab,
Webull, Public. (Ally is not supported by this repository.)

### Known limitations

- **Chase** 2FA method (mobile-app approval vs. text code) is chosen by
  the upstream `chaseinvest-api` library, not this GUI. If it selects
  mobile-app approval, approve on your phone when prompted.
- Multi-account per broker and multi-user are planned for a later
  revision (the credential store already supports multiple accounts).

## Roadmap

### Phase 2 — Extended-hours limit orders

**Goal.** Place orders correctly across pre-market, regular, and
post-market sessions.

**Rule.** Regular hours → market order, time-in-force `day`. Pre-market
and post-market → **limit** order, time-in-force **GTC**
(good-till-cancelled), with the limit price derived from a live quote
for the symbol.

**Why.** Most brokers reject market orders outside regular hours;
extended-hours orders must be limit and are often flagged
extended-hours-eligible. A computed limit (e.g. buy at `ask + buffer`,
sell at `bid - buffer`) lets pre/post orders rest until filled.

**What the codebase already provides.** `StockOrder` supports
`set_price("market" | "limit" | float)` and `set_time("day" | "gtc")`.
The gap: `arg_parser` hardcodes `market`/`day` and never exposes them,
and each broker's `*_transaction` mostly places market orders with only
ad-hoc limit fallback.

**Planned approach.**
1. Add a UI-agnostic core module for (a) US-equity session detection
   (pre ≈04:00–09:30 ET, regular 09:30–16:00, post 16:00–20:00 ET,
   incl. holidays/half-days, timezone-correct) and (b) a single
   consistent live-quote source.
2. Have the GUI runner construct `StockOrder` directly with the
   computed `price`/`time` instead of going through `arg_parser`.
3. Maintain a per-broker capability matrix (limit / GTC /
   extended-hours support, bounded by each upstream library). Enable
   the limit path only where genuinely supported; warn/fall back
   otherwise.
4. GUI: session indicator, configurable limit buffer (cents or %), and
   a dry-run preview of the exact limit price before any live order.

**Open decisions.**
- Quote source (which broker lib vs. an external market-data API;
  reliability/latency matters for limit pricing).
- Limit-buffer policy and defaults (unfilled vs. overpay trade-off).
- Which of the dependable brokers (Fennel, Robinhood, BBAE, DSPAC,
  Public) actually support limit + GTC + extended-hours; this is
  per-broker and gated by upstream libraries.

**Risk.** A stale quote or wrong limit calc places a bad real-money
order. Dry-run-first and conservative defaults are mandatory.
