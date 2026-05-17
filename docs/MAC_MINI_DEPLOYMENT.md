# AutoRSA — Mac Mini (macOS 26) Deployment Guide

A single, self-contained guide to run the AutoRSA Python software on a
Mac Mini M2 (8 GB) running **macOS 26**, from a clean machine with no
prior developer tooling or GitHub use. ~45–60 min.

Every command is run in **Terminal** (Finder → Applications →
Utilities → Terminal). Copy/paste one block at a time.

---

## 0. What you are deploying

| Component | What it does | How it runs |
|---|---|---|
| **GUI** (`streamlit`) | Credentials, manual trades, Signals dashboard, Ledger, Sessions health | On demand, in a browser |
| **EDGAR producer** (`python -m src.edgar`) | Scrapes SEC/EDGAR → writes `GUI_QUEUE` | `launchd`, every 30 min |
| **Shadow executor** (`python -m src.autoexec`) | Reports what it *would* buy — **no orders** | `launchd`, every 30 min |
| **Session audit** (`python -m src.session_audit`) | Read-only broker session-health (🟢/🟡/🔴) | on demand / `launchd` optional |

Nothing places real automated orders yet. Real unattended trading
(M5 phase-2) is gated on separate validation and is **not** enabled by
this guide.

---

## 1. macOS 26 — system configuration

**Software Update** (System Settings → General → Software Update)
- Install the latest macOS 26 point release.
- Turn **on** "Install Security Responses and system files".

**Energy** (System Settings → Energy)
- Computer sleep: **Never** / "Prevent automatic sleeping when the
  display is off" → **On**
- **Start up automatically after a power failure** → **On**
- **Wake for network access** → **On**
- Headless is fine; the display may sleep.

**Network**
- Use **Ethernet**. On your router, add a **DHCP reservation** binding
  the Mini's Ethernet MAC to a fixed internal IP (stable SSH).
- System Settings → General → Sharing → enable **Remote Login** (SSH).
- Enable the macOS **firewall**; disable Screen Sharing / AirDrop /
  Bluetooth if unused.

**FileVault** (System Settings → Privacy & Security → FileVault)
- **On** if the Mini is physically secured (best protection for the
  stored session/credential files). Note: after an unattended reboot
  the Mac waits at the disk-unlock screen until the password is
  entered — `launchd` jobs resume only after unlock.
- If you need fully hands-off power-loss recovery, leave it **Off**
  **and** keep the Google service account scoped to only the one
  spreadsheet (§4).

---

## 2. Install required software (first time on this Mac)

**2a. Xcode Command Line Tools** (gives `git`):
```sh
xcode-select --install
```
Click **Install** in the dialog; wait for it to finish. Verify:
```sh
git --version
```

**2b. Homebrew** (package manager):
```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```
Run the two `eval`/`echo` lines it prints for Apple Silicon, then:
```sh
eval "$(/opt/homebrew/bin/brew shellenv)"
brew --version
```

**2c. GitHub CLI + sign in**:
```sh
brew install gh
gh auth login
```
Choose **GitHub.com → HTTPS → Yes (authenticate git) → Login with a
web browser**. Enter the one-time code in the browser. Verify:
```sh
gh auth status
```

**2d. uv** (Python toolchain — installs the right Python itself):
```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv --version
```

---

## 3. Get the app + dependencies
```sh
gh repo clone ralanleder/auto-rsa ~/auto-rsa
cd ~/auto-rsa
git checkout claude/trading-gui-with-login-xxH0i
uv sync            # installs Python 3.12 + all dependencies
mkdir -p creds/run_logs
```

---

## 4. Google service account (for the sheet)

1. <https://console.cloud.google.com/> → new project `autorsa`.
2. APIs & Services → Library → enable **Google Sheets API**.
3. APIs & Services → Credentials → **Create credentials → Service
   account** → name it → Done.
4. Open it → **Keys → Add key → Create new key → JSON** → download.
5. Note its `client_email`. In Google Sheets, open your **Claud RSA
   Project** spreadsheet → **Share** → add that email as **Editor**,
   uncheck "Notify". Share nothing else with it.
6. Put the key on the Mini and lock it down:
```sh
mv ~/Downloads/<the-key>.json ~/auto-rsa/creds/edgar-sa.json
chmod 600 ~/auto-rsa/creds/edgar-sa.json
```
7. Apply Apps Script patch **item 8** (`writeGuiQueue_`) from
   `docs/appscript/README.md` to your bound Apps Script so the
   `GUI_QUEUE` tab is populated (the Python producer also writes it;
   both are idempotent by KEY).

---

## 5. Fidelity unattended login (TOTP)

You added an authenticator (TOTP) secret to your Fidelity account.
In the **GUI** (§7) Credentials tab, in the Fidelity form, paste that
secret into **"TOTP secret (optional)"** and save. Fidelity will then
log in automatically with no SMS/prompt. (Leaving it blank stores
"NA" and Fidelity falls back to interactive SMS — which is fine
attended, but an unattended run will fail fast with a clear message
instead of hanging.)

---

## 6. Smoke tests (no orders, no writes)
```sh
cd ~/auto-rsa
# Producer dry run (prints rows, writes nothing):
RSA_SEC_USER_AGENT="Your Name you@email.com" \
  .venv/bin/python -m src.edgar --window 14
# Session health (read-only):
.venv/bin/python -m src.session_audit
```
Both should print output and exit without error.

---

## 7. Run the GUI (on demand)
```sh
cd ~/auto-rsa
.venv/bin/python -m streamlit run src/gui/app.py
```
Open the printed URL in a browser. Use it to: set the vault password,
enter broker credentials (incl. Fidelity TOTP), paste the Google Sheet
connection (Signals tab → service-account JSON + spreadsheet URL),
pick sub-account filters, run manual trades, and watch the Ledger /
Broker-sessions panels. Stop with `Ctrl-C`.

---

## 8. Scheduled jobs (launchd)

**8a. EDGAR producer** (writes GUI_QUEUE every 30 min):
```sh
cd ~/auto-rsa
sed -e "s|__MACOS_USER__|$(whoami)|g" \
    -e "s|__REPO_DIR__|$HOME/auto-rsa|g" \
    -e "s|__SA_KEY_PATH__|$HOME/auto-rsa/creds/edgar-sa.json|g" \
    -e "s|__SPREADSHEET_ID__|<YOUR_SPREADSHEET_ID>|g" \
    -e "s|__SEC_CONTACT_NAME_AND_EMAIL__|Your Name you@email.com|g" \
    deploy/macmini/com.autorsa.edgar.plist \
  | sudo tee /Library/LaunchDaemons/com.autorsa.edgar.plist >/dev/null
sudo chown root:wheel /Library/LaunchDaemons/com.autorsa.edgar.plist
sudo chmod 644 /Library/LaunchDaemons/com.autorsa.edgar.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/com.autorsa.edgar.plist
sudo launchctl enable system/com.autorsa.edgar
```

**8b. Shadow executor** (reports would-buys; **no orders**):
```sh
cd ~/auto-rsa
sed -e "s|__MACOS_USER__|$(whoami)|g" \
    -e "s|__REPO_DIR__|$HOME/auto-rsa|g" \
    -e "s|__SA_KEY_PATH__|$HOME/auto-rsa/creds/edgar-sa.json|g" \
    -e "s|__SPREADSHEET_ID__|<YOUR_SPREADSHEET_ID>|g" \
    -e "s|__OPTIONAL_WEBHOOK_URL__||g" \
    deploy/macmini/com.autorsa.autoexec-shadow.plist \
  | sudo tee /Library/LaunchDaemons/com.autorsa.autoexec-shadow.plist >/dev/null
sudo chown root:wheel /Library/LaunchDaemons/com.autorsa.autoexec-shadow.plist
sudo chmod 644 /Library/LaunchDaemons/com.autorsa.autoexec-shadow.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/com.autorsa.autoexec-shadow.plist
```

**Verify / force a run:**
```sh
sudo launchctl kickstart -k system/com.autorsa.edgar
tail -n 40 ~/auto-rsa/creds/run_logs/edgar.err.log
tail -n 40 ~/auto-rsa/creds/run_logs/autoexec-shadow.err.log
```
Compare the shadow "WOULD BUY" lines against your Apps Script feed /
`hist_alerts_v1` for a week+ before any real unattended trading is
considered.

**Kill switch (instant, any time):**
```sh
touch ~/auto-rsa/creds/AUTOEXEC_DISABLED      # shadow/exec become no-ops
```

---

## 9. Corpus regression guards (optional, recommended)

Activates the precision tests. In Google Sheets, **File → Download →
CSV** for each tab and place under `~/auto-rsa/edgar_tests/fixtures/`:
- `hist_alerts_v1` tab  → `hist_alerts_v1.csv`
- SCORER/ANNOUNCEMENTS tab (with `FRACTIONAL_EVIDENCE`,
  `FRACTIONAL_POLICY`) → `corpus_evidence.csv`
```sh
cd ~/auto-rsa
.venv/bin/python -m pytest edgar_tests/corpus_test.py -q -s
```
`-s` prints baseline precision / false-ROUND_UP numbers. CSVs are
gitignored (your data stays local).

---

## 10. Env var reference

| Variable | Component | Meaning |
|---|---|---|
| `RSA_SHEETS_SA_JSON` | producer/shadow | SA key: inline JSON or `@/path` |
| `RSA_SHEETS_ID` | producer/shadow | spreadsheet ID or URL |
| `RSA_SHEETS_WORKSHEET` | producer/shadow | tab (default `GUI_QUEUE`) |
| `RSA_SEC_USER_AGENT` | producer | `"Name email"` for SEC requests |
| `RSA_AUTO_BROKERS` | shadow | allow-list (Tier-1 by default) |
| `RSA_AUTO_DISABLED=1` | shadow | kill switch (also `creds/AUTOEXEC_DISABLED`) |
| `RSA_SESSION_TTL_DAYS` | session audit | session freshness TTL (default 6) |
| `RSA_SESSION_TTL_OVERRIDES` | session audit | JSON `{broker: days}` |
| `RSA_UNATTENDED=1` | engine | fail-fast instead of prompting (headless) |

GUI-managed values live in the encrypted vault; only the `launchd`
jobs need env, set inside their plists.

---

## 11. Maintenance

**Update to latest code:**
```sh
cd ~/auto-rsa && git pull && uv sync
sudo launchctl kickstart -k system/com.autorsa.edgar
sudo launchctl kickstart -k system/com.autorsa.autoexec-shadow
```
**Uninstall a job:**
```sh
sudo launchctl bootout system/com.autorsa.edgar
sudo rm /Library/LaunchDaemons/com.autorsa.edgar.plist
```
**Health at a glance:** `python -m src.session_audit` (exit 1 if any
broker session needs a manual re-login), or the GUI **Status → Broker
sessions** panel.

---

## 12. Safety notes

- `creds/` is fully gitignored — keys, session files, ledger, logs are
  never committed.
- The producer/shadow are idempotent by KEY; running alongside the
  Apps Script feed never double-queues.
- The ledger blocks double-buys per source **and** economically
  (same real split via two feeds).
- No automated real orders are enabled by this guide. Manual trades
  via the GUI require a typed `EXECUTE` confirmation. Quantity for
  reverse-split plays is hard-capped at 1 share.
- Outstanding before any real unattended trading: M1 market-hours
  live-verification and a clean multi-week shadow track record.
