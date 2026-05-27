# Design: license-gated parent-broker count (FOR REVIEW)

Status: **proposal, not built.** Goal: cap how many **parent
brokerage logins** a given install can configure, with three tiers
that scale from "trying it out" to "operator-only", and an
enforcement model that survives a friend trying to bypass it
casually but doesn't require a determined attacker to fail.

Context: this is shared only with trusted friends and the operator
explicitly said "i cannot take any chances" re reverse-engineering.
That puts us firmly in the **online-activation + signed token**
camp — anything purely offline is patchable in one diff and shippable
back out to other friends. Two non-negotiables: **the friend never
sees a license key or hardware ID being typed/copied during normal
use** (one-time activation, then invisible), and **the operator can
revoke a license without shipping a new build**.

---

## 1. Honest threat model (read first)

Same shape as the Windows installer doc:
- The check runs on the friend's machine; the binary contains the
  enforcement code. A motivated attacker with Nuitka knowledge can
  patch it. We can only **raise the bar**.
- The bar matters: the difference between "click a checkbox to add
  account #6" and "patch a Nuitka-compiled binary, fake an HTTPS
  endpoint, forge an Ed25519 signature" is what gets us from
  honor-system to actual deterrence.
- **The only protection against a determined attacker is not shipping
  the crown jewels.** The license layer is here to discourage *casual*
  abuse (a friend adding a 6th broker without asking) and to give the
  operator a revocation lever, not to defeat a reverse engineer.

What we are NOT trying to do:
- Per-trade kill switches, per-account billing, usage telemetry
  beyond activation/refresh, or anything resembling DRM theater.
- Brick the tool when offline. A cached signed token works for a
  generous grace window so flaky home internet ≠ failed run.

## 2. Tiers — what counts and what doesn't

A **parent brokerage login** is one row in the GUI Credentials tab.
"Chase" with 8 sub-accounts under one login = **1**. A friend with
Chase + Fidelity + Robinhood = **3**.

| Tier      | Parent brokerage logins | Intended audience           |
|-----------|------------------------|------------------------------|
| Basic     | 1                      | Trying it out               |
| Advanced  | 2–5                    | Active user                 |
| Mod       | unlimited              | Operator / power user       |
| Unlicensed| 1 (Basic-equivalent)   | Pre-activation grace state  |

Sub-accounts within a parent login are **not** counted — those are
defined by the brokerage, not the user, and counting them would
penalize Chase / Fidelity users for things they can't control.

## 3. License model

```
license_id        : UUID, generated when the operator issues the license
license_key       : opaque random string, what the friend types in
                    (e.g. "rsa-9HQX-7P3N-MEZA"), the only thing
                    transmitted from friend to operator
tier              : "basic" | "advanced" | "mod"
hardware_id       : bound on first activation; rejected if mismatched after
issued_at         : timestamp
expires_at        : timestamp (default 1 year out; renewable)
status            : "active" | "revoked"
notes             : operator-only freeform (who it's for, when granted)
```

The friend never types or sees `license_id`. They get one
human-friendly `license_key` from the operator out-of-band (Signal,
email, whatever).

## 4. Activation flow (one-time, GUI-driven)

1. Friend installs the tool. On first launch the GUI shows a banner:
   **"Unlicensed (Basic — 1 broker). Activate to unlock more."**
2. Friend pastes their `license_key` into a "License" tab.
3. GUI computes a stable hardware fingerprint (§7) and POSTs:
   ```
   POST https://license.<your-domain>/activate
   Content-Type: application/json
   { "license_key": "rsa-9HQX-7P3N-MEZA",
     "hardware_id": "h_5f3a9c…",
     "hostname_hash": "8e2a…",   # SHA-256 of hostname, not the hostname
     "app_version": "0.7.2",
     "platform": "darwin-arm64" }
   ```
4. Server validates the key, binds `hardware_id` if not yet set
   (or rejects with HTTP 409 if already bound to a different
   machine), and returns:
   ```
   { "token": "<base64 url-safe>",
     "tier": "advanced",
     "account_cap": 5,
     "hardware_id": "h_5f3a9c…",
     "issued_at": "2026-05-27T20:00:00Z",
     "expires_at": "2026-06-26T20:00:00Z",
     "license_id": "1f0a…",
     "signature": "<Ed25519 over the canonical JSON above>" }
   ```
5. The tool verifies the signature with the **embedded public key**,
   verifies `hardware_id` matches the current machine, and writes
   the token to `creds/license.token` (chmod 600 on POSIX).
6. The banner flips to **"Advanced (5 brokers, expires Jun 26)"**
   and the broker grid unlocks accordingly.

Tokens are short-lived (default **30 days**) and silently refreshed
in the background on each app start when older than 7 days. A
failed refresh due to network issues doesn't fail the run — it just
keeps the cached token until it actually expires.

## 5. Enforcement points in the code

A single source of truth:

```python
# src/license/manager.py
def current_tier() -> Tier        # "basic" | "advanced" | "mod" | "unlicensed"
def account_cap() -> int | None    # None = unlimited (Mod)
def can_add_broker(current_count: int) -> tuple[bool, str | None]
def status_summary() -> dict       # for the GUI banner
```

Every gate calls into this. There are exactly four:

1. **`vault.add_broker_credentials(...)`** — refuses to persist a
   new broker login if `current_count >= cap`. Friend's existing
   brokers are untouched (no auto-deletion on tier downgrade — see
   §11 grace behavior).
2. **GUI Credentials tab** — broker tiles past the cap render
   disabled with a "Upgrade required" hover. Prevents the friend
   from going down the wrong path before discovering the limit.
3. **`fun_run` engine preflight** — at run start, drops any broker
   whose count puts the run over the cap with a clear log line,
   so a stale vault from before a downgrade can't sneak through.
4. **Run-progress sentinel** — emits `LICENSE\t<tier>\t<cap>` once
   per run so the GUI activity bar can display the gate in-context.

Concentrating gates here means a future "what tier am I?" check
adds one call site, not five.

## 6. Cryptographic shape

- **Ed25519** (small keys, fast verify, well-understood). RSA-2048
  also works; Ed25519 is the obvious modern default.
- **Operator** holds the signing private key on a single machine
  (not in the repo, not in the binary, not on the activation
  server — the server has its own per-deploy key for HTTPS only).
- **Public key** is embedded as a constant in the compiled binary
  (a 32-byte literal). Nuitka makes it harder to swap out than a
  text file, but it is **not invisible** — accept that.
- **Canonical signing**: sort keys, no whitespace, UTF-8 JSON →
  raw bytes → Ed25519 sign. Same canonicalization on the verify
  side. Spec the algorithm in this doc and pin it in code so a
  future "let's swap to JWT" doesn't silently change the contract.
- **Clock skew**: allow ±5 minutes on `issued_at`. Tokens whose
  `expires_at` is in the past by more than the grace window (§11)
  fall back to Basic.

## 7. Hardware fingerprint

The fingerprint is the load-bearing piece that stops one license
from being used on five friends' machines. It must be **stable
across reboots and software updates** but **change on a different
machine**.

Recommended inputs, in priority order, with the first available
winning per platform:

- **macOS**: `IOPlatformUUID` from `ioreg` (changes only on
  motherboard replacement). Fallback: hardware UUID from
  `system_profiler`.
- **Windows**: `MachineGuid` from
  `HKLM\SOFTWARE\Microsoft\Cryptography`. Fallback: BIOS serial via
  WMI.
- **Linux**: `/etc/machine-id` (set at first boot, stable for life
  of the install).

Then: `hardware_id = "h_" + SHA256(platform_id + app_install_salt)[:24]`.

The `app_install_salt` is a per-install random value stored in the
vault so the friend's fingerprint isn't trivially correlatable
across tools. **Never** send the raw platform UUID anywhere — only
the salted hash.

What we **don't** use (and why):
- MAC addresses: unstable (dock changes, NIC swap), spoofable.
- Hostname: friends rename machines.
- Disk serial: changes when the friend reinstalls macOS.
- IP address: useless, changes daily.

## 8. Server: Cloudflare Worker + KV

Why Cloudflare:
- Free tier (100K req/day, 1 GB KV) is roughly 10,000× what this
  needs at friend-scale.
- Edge deploy = near-zero activation latency from anywhere.
- No server to patch; the Worker is the whole backend.

Endpoints:

```
POST /activate       { license_key, hardware_id, hostname_hash, ... }
                     → 200 { token, ... } | 409 already bound elsewhere
                     | 410 revoked | 404 unknown key

POST /refresh        { token }       (re-signs with fresh expires_at)
                     → 200 { token } | 401 invalid | 410 revoked

POST /admin/issue    { tier, notes, expires_at } (Bearer admin secret)
                     → 200 { license_key }   stored in KV

POST /admin/revoke   { license_id }          (Bearer admin secret)
                     → 200

GET  /admin/list     (Bearer admin secret)
                     → 200 [ { license_id, tier, hardware_id, ... } ]
```

KV layout:
- `lic:<license_id>` → full license record
- `key:<license_key>` → license_id (lookup index)
- `hw:<hardware_id>` → license_id (detects "same machine, new key"
  attempts; logs but doesn't auto-reject)
- `audit:<license_id>:<ts>` → activation/refresh events (90-day TTL)

Admin secret is a single long random string, stored in 1Password,
rotated yearly. Admin endpoints are also IP-allowlisted to the
operator's home/work IPs as belt-and-suspenders.

## 9. Operator workflow

Issuing a license:

```
$ rsa-license issue --tier advanced --for "Alice" --expires 1y
Issued: rsa-9HQX-7P3N-MEZA  (license_id 1f0a…, advanced, exp 2027-05-27)
```

`rsa-license` is a 100-line CLI that wraps the admin endpoints. It
prints the human-friendly `license_key` once. The operator copies
it into Signal and sends it to Alice.

Revoking:

```
$ rsa-license revoke 1f0a…
Revoked. Next refresh by this license will return 410; cached
token still works for up to 7 more days (grace window).
```

Listing:

```
$ rsa-license list
LICENSE_ID  TIER      HW_BOUND  LAST_SEEN     EXPIRES     NOTES
1f0a…       advanced  yes       2 days ago    2027-05-27  Alice
2b8c…       basic     no        never         2026-08-30  trial — Bob
9f44…       mod       yes       1 hour ago    2030-12-31  operator (self)
```

## 10. GUI surfaces

One new tab: **License**.

- Banner shows current tier, account cap, expiry date, last
  refresh, and the masked license key (`rsa-…MEZA`).
- "Refresh now" button (calls the refresh endpoint immediately).
- "Show hardware ID" button → reveals the fingerprint so the
  friend can give it to the operator if they need to migrate to a
  new machine.
- "Activate with new key" button → unbinds the current token,
  prompts for a new key, re-activates.
- Status badge in the sidebar: 🟢 Advanced · 5/5 brokers · ✓ Active.

The Credentials tab gains a discreet "Upgrade your license for
more brokers" footer note (no upsell theater).

## 11. Grace behavior (the "don't brick the tool" rules)

- **Token expired, network reachable**: refresh transparently.
  Friend sees nothing.
- **Token expired, refresh fails (network)**: tool keeps running
  for 7 days at the cached tier, shows a yellow banner
  ("License needs to refresh — last attempt failed"). After 7
  days, falls back to Basic (1 broker) with a red banner.
- **License revoked (server returns 410)**: tool keeps running
  for 7 days at the cached tier, shows a red banner immediately.
  After 7 days, falls back to Basic.
- **Tier downgraded** (Mod → Advanced, etc.) with current brokers
  exceeding new cap: brokers above the cap are **not deleted**;
  they're flagged "over cap — orders will skip" and the
  per-broker run progress shows them as ⚪ skipped. Friend can
  remove brokers manually to get back under.
- **Hardware change**: friend hits the "Show hardware ID"
  button, sends it to the operator, operator runs
  `rsa-license rebind 1f0a… h_new…`. No automatic re-bind —
  that defeats the binding.

## 12. Code layout

```
src/license/
  __init__.py
  manager.py          # current_tier(), account_cap(), can_add_broker()
  client.py           # POST /activate, POST /refresh
  fingerprint.py      # hardware_id() per platform
  verify.py           # Ed25519 verify + canonical JSON
  tiers.py            # TIER_CAPS = {"basic": 1, "advanced": 5, "mod": None}
  token_store.py      # creds/license.token I/O (chmod 600)
server/license-worker/
  src/index.ts        # Cloudflare Worker handlers
  src/kv.ts           # KV layout helpers
  src/sign.ts         # Ed25519 sign (server-side, uses WebCrypto)
  wrangler.toml
admin/
  rsa_license.py      # operator CLI
```

Files outside `src/license/` only ever call `manager.py`. That's
the API surface — if a future enforcement point needs a fact about
the license, it's added there.

## 13. Tests (golden vectors, tamper resistance)

- Signature verify against a checked-in `golden.json` so a future
  "let's tweak the canonicalization" PR breaks loudly.
- Hardware fingerprint stability: same inputs → same hash across
  runs (lru_cache safe).
- Tamper tests: bit-flip the token → fail. Edit expires_at →
  fail. Edit tier → fail. Hardware_id mismatch → fail. Clock
  shift past skew → fail. All assert the specific reject reason.
- `can_add_broker` boundary tests: cap=1 with 0/1/2 brokers,
  cap=5 with 4/5/6, cap=None always allows.
- Grace-window timeline tests with frozen-time.

## 14. Open questions for review

1. **Naming**: "Basic / Advanced / Mod" — "Mod" reads
   moderator-of-something. Suggest **"Operator"** for the
   unlimited tier (matches our existing operator-vs-friend
   language).
2. **License key format**: human-friendly hyphenated like
   `rsa-9HQX-7P3N-MEZA` (16 chars of base32 = ~80 bits of entropy)
   reads fine over Signal. Long enough that brute-forcing the
   activation endpoint is hopeless even without rate limits.
3. **Worker domain**: `license.<your-domain>` keeps it under your
   existing DNS. Alternative: a `*.workers.dev` subdomain (free,
   ugly URL, fine for a few friends).
4. **Self-license bootstrap**: the operator needs their own Mod
   license to actually use the tool. `rsa-license issue --tier mod
   --for "operator (self)"` is fine; just make sure step 1 of the
   build process is "issue your own license."
5. **Do we count `unlicensed` runs at all in cost?** They're free
   on Cloudflare. But it's worth deciding whether unlicensed mode
   even allows ORDER placement (current proposal: yes, capped at 1
   broker — Basic-equivalent — so the friend can confirm the tool
   works before paying / asking for an upgrade).
6. **Migration**: existing friends today have no license. First
   release with enforcement: their existing vaults keep working
   (no broker deletion), but adding the 2nd broker requires
   activation. Spec'd above; calling it out so it's not a surprise.

## 15. What we don't ship

- No license check on holdings-only runs (read-only) at first; only
  on order placement. Reduces support burden during rollout.
- No telemetry beyond activation/refresh metadata (no broker names,
  no ticker symbols, no order counts).
- No "license server" running on the operator's home machine — the
  Worker is the whole backend so the operator's laptop being asleep
  never breaks a friend's activation.
- No paid-tier / billing integration. This is a gate for trusted
  friends, not a SaaS product.

---

## Build sequencing if approved

1. `src/license/` module + `tiers.py` + tests (~half day, in-repo,
   no server yet).
2. `manager.py` gates wired into vault + GUI (banner / disabled
   tiles). Manual JSON token for now — no activation flow.
3. Cloudflare Worker + KV + admin CLI (~half day).
4. Activation flow end-to-end + golden signature tests.
5. Nuitka rebuild with public key embedded (folds into the
   existing Windows installer plan).
6. Issue operator a Mod license, migrate two trusted friends to
   Advanced, observe for a week.

Total: ~3 working days of focused effort, plus a week of
soak-testing with real friends before opening up further.
