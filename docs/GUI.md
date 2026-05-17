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
