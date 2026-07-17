# License administration & troubleshooting

Everything you (the operator) need to issue, manage, reset, and troubleshoot
license keys — and to recover if something goes wrong. Written so you can come
back to it months later and not have to re-derive anything.

The day-to-day parts need **no terminal** — they're all in the web console.
The rare recovery parts (rotating secrets/keys) use the terminal once.

---

## 1. How the system works (the 60-second model)

- Your **Cloudflare Worker** (`rsa-license.ralanleder.workers.dev`) is the
  license server. It holds the **private** Ed25519 signing key and a **KV**
  namespace (`LICENSES`) with one record per license.
- Each friend's app has the matching **public key baked in** (`PUBLIC_KEY_B64`
  in `src/license/_keys.py`). The app trusts the *signature*, not the server —
  a rogue server can't mint a token the app will accept.
- **Activation:** a friend pastes their key in the app's **License** section.
  The Worker binds that key to their machine's hardware fingerprint and returns
  a short-lived (30-day) **signed token**. The app re-checks (`/refresh`) as it
  runs, so **revoke** and the **kill switch** bite on the next check.
- **Tiers** decide how many brokers/accounts a friend can use:

  | Type (console label) | tier id | Brokers | Accounts |
  |---|---|---|---|
  | Operator (you) | `operator` | unlimited | unlimited |
  | Friend — Main | `friend_main` | many | 1 per broker |
  | Friend — Lite | `friend_lite` | 1 at a time | 1 |
  | Advanced | `advanced` | up to 5 | — |
  | Basic | `basic` | 1 | — |

- **Kill switch:** a global "pause trading" flag you flip if a crucial bug
  ships. It fails *open* on a network blip (a Cloudflare hiccup never freezes a
  friend); revoke is the hard backstop.
- **Monitoring (friend build):** friends' apps send a small, **disclosed,
  anonymous** diagnostic beacon (app version, coarse error category, run
  counts) and the Worker tracks per-license activation/rebind churn to flag
  license-sharing. It never includes credentials, accounts, holdings, or
  trades. See §3 "Monitoring" and the in-app disclosure.

Where things live:
- Worker code + console: `server/license-worker/` (`src/index.js`,
  `src/admin_ui.js`). Deploy with `npm run deploy`.
- Secrets: `SIGNING_KEY_PEM` and `ADMIN_SECRET` (Cloudflare Worker secrets —
  never in the repo). Set via `npm run secret:key` / `npm run secret:admin`.
- One-time keypair generator: `server/license-worker/gen-keys.py`.
- Client verification: `src/license/verify.py`, tiers in `src/license/tiers.py`.

---

## 2. First-time setup (already done — recap for reference)

You only do this once. If you ever start fresh, see
`server/license-worker/README.md` §"One-time setup". In short:

1. `python server/license-worker/gen-keys.py` → makes the keypair +
   `ADMIN_SECRET`, prints `PUBLIC_KEY_B64`.
2. Paste `PUBLIC_KEY_B64` into `src/license/_keys.py`, set `ACTIVATION_URL` to
   your Worker URL, commit both.
3. From `server/license-worker/`: `npm run secret:key` (paste the PEM),
   `npm run secret:admin` (paste the secret), `npm run test:golden`,
   `npm run deploy`.

---

## 3. Day-to-day: issue and manage keys (no terminal)

Open **`https://rsa-license.ralanleder.workers.dev/admin`**, paste your
`ADMIN_SECRET` once (tick "Remember on this device" on your own machine).

- **Generate a key:** pick the **Type** from the dropdown, add a **note** (who
  it's for), optionally set an expiry, click **Generate**, click **Copy**. Send
  the key to your friend; they paste it into the app's **License** section.
- **See everything:** **Refresh** lists every license — type, status,
  whether it's bound to a machine, notes, expiry.
- **Reset a machine binding:** **Unbind** (see §4.1).
- **Turn a key off:** **Revoke** (see §4.2).
- **Pause everyone:** the **Kill switch** panel (see §4.4).

### Distributing the app
The repo is private, so friends can't pull GitHub build artifacts. Flow:
build the installer in CI (Actions → **Windows Installer** → Run workflow, or
push a `win-v*` tag), **download the artifact once**, upload that
`AutoRSA-Setup.exe` to **Google Drive**, and share the Drive link with the
friend *after* you've provisioned their key.

### Monitoring: activity & license-sharing
The console surfaces two privacy-safe signals, both in the `/admin` page:

- **Recent activity** — a feed of the anonymous diagnostics friends' apps
  report: app version, a coarse error category (e.g. `broker_errors`), and run
  counts (brokers / errors). Use it to spot a broken build or a friend stuck on
  an old version. It contains **no** account, credential, holding, ticker, or
  dollar data.
- **License-sharing (churn)** — the **Machines** column shows how many distinct
  computers have activated a key, with a **⚠ churn** flag when a key shows
  repeated churn (≥3 machines, ≥3 rebinds, or ≥3 blocked second-machine
  attempts). Hover the cell for the exact activation / rebind / blocked counts.
  A friend moving computers once is normal; *repeated* churn is a sharing
  signal — follow up, or **Revoke** and reissue.

What friends see: a one-line disclosure in the app's **License** section.
Diagnostics are on by default in a friend build; disable with
`RSA_TELEMETRY=0` (an operator/testing lever — the server-side churn signal
needs no client and can't be turned off from the app).

---

## 4. Resetting keys & common operations

### 4.1 "My friend got a new computer" → Unbind
A license binds to the first machine that activates it. On a new machine the
app shows **"license already bound to another machine."** Fix it with no
terminal:

1. Console → **Existing licenses** → **Refresh**.
2. Find their key (use the note), click **Unbind**, confirm.
3. Tell them to open the app's **License** section and **activate the same key
   again** — it re-binds to the new machine.

(Under the hood this clears the stored hardware fingerprint. The rare case
where you must bind to a *specific* machine id is the `/admin/rebind` endpoint
with a `hardware_id` — terminal only; almost never needed.)

### 4.2 Turn a key off for good → Revoke
Console → **Refresh** → **Revoke** on that row. The friend stops trading on
their next check (within ~a minute of running). Revoke is permanent for that
key — to let them back, issue a **new** key.

### 4.3 Reissue a key (lost it, or want a clean one)
There's no "resend" — keys are random and not stored anywhere but the Worker.
Just **Revoke** the old one (optional) and **Generate** a fresh key of the same
type. Send the new key.

### 4.4 Pause / unpause trading → Kill switch
Console → **Kill switch** panel:
- **Turn ON** with a message → every affected app refuses to place orders and
  shows your message. Use for a crucial bug.
- **"Only pause builds at or below version"** → set e.g. `0.1.0` to pause only
  the buggy builds and let updated ones keep trading.
- **Turn OFF** to resume.

Kill fails *open* on a network error (a Cloudflare blip won't freeze a run). For
a hard stop of one person, use **Revoke**; for everyone, use kill **and** ship a
fix.

### 4.5 Expiry
Keys default to **365 days**. Set a shorter window in the **Valid for (days)**
box when generating. An expired key reads as unlicensed in the app — issue a new
one (or, before it expires, you can't "extend" in the console; reissue).

---

## 5. Recovery / rotation (terminal, rare)

### 5.1 Rotate the `ADMIN_SECRET` (if it leaks)
Anyone with `ADMIN_SECRET` can issue/revoke. If it leaks:
```bash
cd server/license-worker
npm run secret:admin      # enter a NEW secret
npm run deploy
```
Every console session using the old secret stops working immediately. Update
your saved copy (password manager) and re-enter it in the console.

### 5.2 Rotate the signing keypair (nuclear — invalidates ALL licenses)
Only if the **private key** leaks. This makes every already-issued token
invalid; every friend must re-activate with a **new** key you issue.
```bash
python server/license-worker/gen-keys.py --force   # new keypair + admin secret
```
Then: paste the new `PUBLIC_KEY_B64` into `src/license/_keys.py`, commit, ship a
new app build, `npm run secret:key` (new PEM), `npm run deploy`, and reissue
keys. Avoid unless truly compromised.

### 5.3 Back up what matters
- `ADMIN_SECRET` and the signing **private key** (`rsa-signing-key.pem`) →
  password manager. Losing the private key = §5.2 (reissue everyone).
- The KV license records live in Cloudflare; `GET /admin/list` (console
  "Refresh") is your live inventory.

---

## 6. Troubleshooting: what the friend sees → what to do

| Friend's app says… | Cause | Fix |
|---|---|---|
| "license already bound to another machine" | Key activated on a different computer | **Unbind** (§4.1), have them re-activate |
| "This license has been revoked or has expired" | You revoked it, or it passed its expiry | Issue a new key (§4.3) |
| "No valid license… activate your key" | Never activated, or token expired offline | Have them paste the key in **License**; if it fails, check the key exists in the console list |
| "License key not recognized" (404) | Typo in the key, or wrong Worker | Re-copy the key from the console; confirm they're on the current app build |
| "Trading is paused by the operator" (423) | Kill switch is ON | Intended — turn it **OFF** (§4.4) when the fix is out |
| "Activation failed (HTTP 500)" | Worker error (e.g. secret not set) | Check `SIGNING_KEY_PEM`/`ADMIN_SECRET` are set; redeploy; see worker README |
| Activation works but caps feel wrong | Wrong tier issued | Revoke, reissue the correct type (§4.3) |

**Quick server health check** (no license needed):
```bash
curl https://rsa-license.ralanleder.workers.dev/killswitch
# -> {"active":false,"message":"","min_app_version":""}   (server is up)
```

**Verify a friend's license exists / its state:** console → **Refresh**, or
`GET /admin/list`. Every issued key with its tier, binding, and status is there.

---

## 7. Security reminders

- The `ADMIN_SECRET` is the master key to issuing/revoking. Keep it in a
  password manager; only use "Remember on this device" on machines you control.
- The `/admin` console page is safe to leave deployed publicly — without the
  secret it can do nothing (unauthenticated admin actions return 401).
- Never commit the signing **private key** or the `ADMIN_SECRET` (they're
  Worker secrets and `.gitignore`d).
- Friend builds contain **no** admin/signing code — all of that lives only on
  the Worker.
- Diagnostics are **anonymous and disclosed** — app version, coarse error
  category, and integer counts only. The app never transmits credentials,
  account numbers, holdings, tickers, amounts, or the vault, and the beacon is
  token-authenticated so it can't be spoofed. Keep it that way: never add
  account or trade detail to a beacon (the Worker also drops unknown fields).
