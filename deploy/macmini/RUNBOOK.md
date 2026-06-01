# Mac Mini M2 — EDGAR producer setup runbook

Deploy the `python -m src.edgar` GUI_QUEUE producer as an unattended,
reboot-safe `launchd` job. Written for a **clean Mac with no developer
tools and no prior GitHub use**. ~45 min. Every command is run in
**Terminal** (Finder → Applications → Utilities → Terminal).

---

## 1. macOS + security
- Update to the latest macOS 26 point release (System Settings →
  General → Software Update).
- Enable **Install Security Responses and system files** (same screen).
- FileVault: **On** if the device is physically secured (best at-rest
  protection for the service-account key; an unattended reboot then
  stops at the unlock screen until the password is typed). If you need
  fully hands-off power-loss recovery, leave it Off **and** keep the
  service account scoped to only the one spreadsheet.

## 2. Power (System Settings → Energy)
- Computer sleep: **Never** / "Prevent automatic sleeping when the
  display is off" → **On**
- **Start up automatically after a power failure** → **On**
- **Wake for network access** → **On**
- Runs headless; display sleep is fine.

## 3. Network
- Use Ethernet. On the router, add a **DHCP reservation** binding the
  Mini's Ethernet MAC to a fixed internal IP.
- System Settings → General → Sharing → enable **Remote Login** (SSH).
- Enable the macOS **firewall**; disable Screen Sharing / AirDrop /
  Bluetooth if unused.

## 4. Install required software (first time on this Mac)
Run these in Terminal, in order. Each line is safe to copy/paste.

**4a. Xcode Command Line Tools** (provides `git` and compilers):
```sh
xcode-select --install
```
A dialog appears — click **Install**, accept, wait for it to finish.
Verify:
```sh
git --version
```

**4b. Homebrew** (package manager):
```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```
At the end it prints two `echo ... >> ~/.zprofile` / `eval` lines for
**Apple Silicon** — run exactly those, then:
```sh
eval "$(/opt/homebrew/bin/brew shellenv)"
brew --version
```

**4c. GitHub CLI + sign in** (so the private repo can be cloned/updated):
```sh
brew install gh
gh auth login
```
Choose: **GitHub.com** → **HTTPS** → **Yes** (authenticate git) →
**Login with a web browser**. Copy the one-time code, press Enter,
sign in to your GitHub account in the browser. Verify:
```sh
gh auth status
```

**4d. uv** (Python toolchain — installs the right Python itself):
```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv --version
```

## 5. Get the app + install dependencies
```sh
gh repo clone ralanleder/auto-rsa ~/auto-rsa
cd ~/auto-rsa
git checkout claude/trading-gui-with-login-xxH0i
uv sync          # installs Python 3.12 + all dependencies
mkdir -p creds/run_logs
```

## 6. Service-account key (write scope)
- Save the producer's service-account JSON to
  `~/auto-rsa/creds/edgar-sa.json` (use `scp`, AirDrop to a file, or
  paste with `nano ~/auto-rsa/creds/edgar-sa.json`).
- Lock it down:
```sh
chmod 600 ~/auto-rsa/creds/edgar-sa.json
```
- In Google Drive, share **only** the GUI_QUEUE spreadsheet with that
  service account's `client_email` (Editor). Nothing else.

## 7. Smoke test (dry run — makes no writes)
```sh
cd ~/auto-rsa
RSA_SEC_USER_AGENT="Your Name you@email.com" \
  .venv/bin/python -m src.edgar --window 14
```
Confirm it prints a GUI_QUEUE header + rows and exits without error.

## 8. Install the scheduled job (launchd)
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

## 9. Verify
```sh
sudo launchctl kickstart -k system/com.autorsa.edgar   # run now
tail -n 40 ~/auto-rsa/creds/run_logs/edgar.err.log
```
A run logs `N alert-worthy play(s).` and appends only new KEYs. It then
repeats automatically every 30 minutes and on every reboot.

## 10. Update / uninstall
```sh
# Update to the latest code:
cd ~/auto-rsa && git pull && uv sync
sudo launchctl kickstart -k system/com.autorsa.edgar

# Uninstall:
sudo launchctl bootout system/com.autorsa.edgar
sudo rm /Library/LaunchDaemons/com.autorsa.edgar.plist
```

## 10a. Optional: weekly encrypted backup to Google Drive

Bundles `creds/vault.json` + `creds/ledger.db` + `creds/license.token`,
encrypts with a separate passphrase, uploads to a Google Drive folder
shared with the same SA you set up for Sheets. Runs Sundays at 03:00
local; manual button in the GUI sidebar always works regardless.

**Configure first** (via the GUI):
1. In Drive, create a folder named `AutoRSA Backups`. Share it with
   the SA's `client_email` (Editor). Copy the folder ID from the URL.
2. In the GUI sidebar → **🔐 Backups (Google Drive)**: paste the
   folder ID + a backup passphrase + retention count → **Save**.
3. (Optional) Click **📤 Back up now** once to verify uploads work
   before scheduling.

**Install the launchd job**:
```sh
sed -e "s|__MACOS_USER__|$USER|g" \
    -e "s|__REPO_DIR__|$PWD|g" \
    -e "s|__SA_KEY_PATH__|$PWD/creds/sa-key.json|g" \
    deploy/macmini/com.autorsa.backup.plist \
  | sudo tee /Library/LaunchDaemons/com.autorsa.backup.plist >/dev/null
sudo chown root:wheel /Library/LaunchDaemons/com.autorsa.backup.plist
sudo chmod 644 /Library/LaunchDaemons/com.autorsa.backup.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/com.autorsa.backup.plist
sudo launchctl enable system/com.autorsa.backup
```

Check it:
```sh
tail -200 creds/run_logs/backup.out.log
sudo launchctl kickstart -k system/com.autorsa.backup   # run now (verify)
```

Uninstall:
```sh
sudo launchctl bootout system/com.autorsa.backup
sudo rm /Library/LaunchDaemons/com.autorsa.backup.plist
```

## 11. Optional: shadow executor (M5 phase 1 — no orders)

Reports what it *would* buy from GUI_QUEUE. **Places no orders,
contacts no brokers, writes nothing** — pure selection validation.
Install exactly like §8 but with the shadow plist:

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
Kill switch any time: `touch ~/auto-rsa/creds/AUTOEXEC_DISABLED`
(or `RSA_AUTO_DISABLED=1`) makes every run a no-op. Watch it with
`tail -f ~/auto-rsa/creds/run_logs/autoexec-shadow.err.log`.
Compare its "WOULD BUY" lines against your Apps Script feed /
`hist_alerts_v1` for a week+ before any real unattended trading is
considered.

Notes: `creds/` is gitignored, so the key and logs are never committed.
The producer is idempotent by KEY, so running alongside the Apps Script
feed never double-queues a play.
