# Build guide: Cloudflare license server + remote kill switch

Status: **build playbook** (the *design* is settled in
`docs/LICENSE_TIERS_DESIGN.md`; this is the concrete how-to). Goal:
give the operator everything needed to (1) create the cryptographic
keys, (2) stand up the Cloudflare Worker + KV, (3) wire activation
into the app on top of the **existing** `src/license/` module, and
(4) have a working **kill switch** so a crucial bug can stop every
friend on their next check-in — without shipping a new build.

> **Why Cloudflare, restated:** the enforcement lives on the friend's
> machine, so a determined reverse-engineer can patch it. This layer
> exists to (a) stop *casual* over-use and (b) give the operator a
> **remote off switch**. That second point is the whole reason the
> user wants this: *"build controls in case I need to prevent them
> from using it (crucial bug)."* The kill switch is the deliverable.

---

## 0. What already exists (you are not starting from zero)

`src/license/` is built and tested:
- `verify.py` — Ed25519 detached-signature verify over **canonical
  JSON** (`sort_keys=True, separators=(",",":"), ensure_ascii=False`).
  Client-side, pure, never raises.
- `manager.py` — `current_tier()`, `account_cap()`,
  `can_add_broker()`, `status_summary()`. The single decision site.
  Already checks signature → hardware binding → expiry (+7-day grace).
- `token_store.py` — reads/writes `creds/license.token` (chmod 600),
  distinguishes "no token" from "corrupt token."
- `fingerprint.py` — per-machine `hardware_id()` with a fallback flag.
- `tiers.py` — `TIER_CAPS` (`unlicensed:1, basic:1, advanced:5,
  operator:None`).
- `_keys.py` — holds `PUBLIC_KEY_B64` (the embedded verify key).

**What's missing and this guide builds:** the keypair, the Cloudflare
Worker (`/activate`, `/refresh`, admin, and the **kill-switch**
endpoints), `src/license/client.py` (the HTTP calls), and the
operator CLI. The canonical-JSON contract in `verify.py` is the
**hard interface** the Worker must match byte-for-byte.

---

## 1. Create the keys

There are **three** distinct secrets. Keep them straight — mixing
them up is the classic footgun.

| Key | Lives where | Purpose | If leaked |
|-----|-------------|---------|-----------|
| **Ed25519 private (signing)** | operator laptop + Worker secret | signs tokens | anyone can mint valid licenses → rotate keypair + reship public key |
| **Ed25519 public (verify)** | embedded in the app (`_keys.PUBLIC_KEY_B64`) | verifies tokens | harmless (it's meant to be shipped) |
| **Admin API secret** | 1Password + Worker secret | authorizes issue/revoke/kill | rotate the Worker secret |

### 1.1 Generate the Ed25519 signing keypair

Do this **once**, offline, on the operator machine. Python (the repo
already depends on `cryptography`):

```python
# scripts/gen_license_keys.py  — run once, then store the output safely
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
import base64

priv = Ed25519PrivateKey.generate()

# Private (raw 32 bytes, base64) — goes to the Worker as a secret + your vault.
priv_raw = priv.private_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PrivateFormat.Raw,
    encryption_algorithm=serialization.NoEncryption(),
)
# Public (raw 32 bytes, base64) — goes into src/license/_keys.py.
pub_raw = priv.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)

print("PRIVATE_KEY_B64 (SECRET — Worker + 1Password):", base64.b64encode(priv_raw).decode())
print("PUBLIC_KEY_B64  (embed in _keys.py):          ", base64.b64encode(pub_raw).decode())
```

- The **public** string goes into `src/license/_keys.py` as
  `PUBLIC_KEY_B64`. This is what `verify.py` already loads. Commit it
  — it's designed to ship.
- The **private** string goes into 1Password (backup) and into the
  Worker as a secret (§3.4). **Never** commit it, never put it in the
  app, never send it to the activation server as request data.

> Matching contract: `verify.py` does
> `Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))`
> and verifies against `canonical_bytes(payload)`. The Worker must
> sign **exactly** `canonical_bytes(payload)` with the raw private key
> above. Same bytes in, same bytes out — that's the whole compat
> requirement.

### 1.2 Generate the admin secret

```
python -c "import secrets; print('rsa_admin_' + secrets.token_urlsafe(32))"
```

Store in 1Password. This authorizes `/admin/*` and the kill switch.

---

## 2. Cloudflare account setup (one time)

1. Create a free Cloudflare account (no domain needed — you'll use
   the free `*.workers.dev` subdomain).
2. Install Wrangler (the Workers CLI): `npm i -g wrangler`.
3. `wrangler login` → authorizes the CLI against your account in the
   browser.
4. Create a KV namespace for license records:
   ```
   wrangler kv namespace create LICENSES
   ```
   Copy the returned `id` into `wrangler.toml` (§3.2).

That's the entire infrastructure. No servers, no VMs, no database. The
free tier (100K requests/day, 1 GB KV) is ~10,000× friend-scale.

---

## 3. The Worker

Layout (matches `docs/LICENSE_TIERS_DESIGN.md` §12):

```
server/license-worker/
  src/index.ts        # request router + handlers
  src/sign.ts         # Ed25519 sign via WebCrypto
  src/kv.ts           # KV key helpers
  wrangler.toml
```

### 3.1 KV layout

```
lic:<license_id>     → { license_id, license_key, tier, hardware_id|null,
                         issued_at, expires_at, status, notes }
key:<license_key>    → license_id            (lookup by the key the friend types)
hw:<hardware_id>     → license_id            (detect "same box, new key")
killswitch:global    → { active: bool, min_app_version?, message }   ← the kill switch
audit:<license_id>:<ts> → activation/refresh event   (90-day TTL)
```

### 3.2 `wrangler.toml`

```toml
name = "rsa-license"
main = "src/index.ts"
compatibility_date = "2024-01-01"

[[kv_namespaces]]
binding = "LICENSES"
id = "<the id from wrangler kv namespace create>"

# Secrets (PRIVATE_KEY_B64, ADMIN_SECRET) are set with `wrangler secret put`,
# never written here.
```

### 3.3 Signing in the Worker (`sign.ts`)

The Worker signs with WebCrypto. The **critical** detail is producing
the same canonical bytes the Python `verify.py` expects:

```ts
// Canonical JSON: sorted keys, no spaces, UTF-8. MUST match
// src/license/verify.py :: canonical_bytes exactly.
function canonicalBytes(payload: Record<string, unknown>): Uint8Array {
  const sortObj = (o: any): any =>
    (o && typeof o === "object" && !Array.isArray(o))
      ? Object.keys(o).sort().reduce((a, k) => (a[k] = sortObj(o[k]), a), {} as any)
      : o;
  const json = JSON.stringify(sortObj(payload)); // JSON.stringify uses "," and ":" — no spaces
  return new TextEncoder().encode(json);
}

async function importPrivateKey(b64: string): Promise<CryptoKey> {
  // Ed25519 raw 32-byte seed → PKCS8 wrapper for WebCrypto import.
  const raw = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  const pkcs8 = new Uint8Array([
    0x30,0x2e,0x02,0x01,0x00,0x30,0x05,0x06,0x03,0x2b,0x65,0x70,0x04,0x22,0x04,0x20,
    ...raw,
  ]);
  return crypto.subtle.importKey("pkcs8", pkcs8, { name: "Ed25519" }, false, ["sign"]);
}

async function signToken(payload: object, privB64: string): Promise<string> {
  const key = await importPrivateKey(privB64);
  const sig = await crypto.subtle.sign("Ed25519", key, canonicalBytes(payload as any));
  // base64url, no padding — verify.py restores padding on its side.
  return btoa(String.fromCharCode(...new Uint8Array(sig)))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
```

> **Test this against Python before shipping.** Sign a fixed payload
> in the Worker, paste the `{payload, signature}` into a Python test
> that calls `verify.verify_token(token, PUBLIC_KEY_B64)`, and assert
> `True`. This is the golden-vector test in
> `LICENSE_TIERS_DESIGN.md` §13 — build it first, because a
> canonicalization mismatch fails silently as "every token invalid."

### 3.4 Set the Worker secrets & deploy

```
cd server/license-worker
wrangler secret put PRIVATE_KEY_B64     # paste the base64 private key from §1.1
wrangler secret put ADMIN_SECRET        # paste the admin secret from §1.2
wrangler deploy
# → https://rsa-license.<your-subdomain>.workers.dev
```

Put that URL in the app as `LICENSE_SERVER_URL` (a constant in
`client.py`, baked into the build). The friend never types it.

### 3.5 Endpoints

```
POST /activate   { license_key, hardware_id, hostname_hash, app_version, platform }
   → 200 { payload:{...}, signature }   (payload has tier, hardware_id, expires_at, license_id)
   → 404 unknown key | 409 bound to a different machine | 410 revoked

POST /refresh    { token }              (re-sign with a fresh expires_at; re-checks kill switch)
   → 200 { payload, signature } | 401 invalid | 410 revoked | 423 killed

GET  /killswitch { hardware_id? }       (cheap, unauthenticated, cacheable)
   → 200 { active: bool, message, min_app_version }

POST /admin/issue    (Bearer ADMIN_SECRET)  { tier, notes, expires_at } → { license_key }
POST /admin/revoke   (Bearer ADMIN_SECRET)  { license_id } → 200
POST /admin/kill     (Bearer ADMIN_SECRET)  { active, message, min_app_version? } → 200
POST /admin/rebind   (Bearer ADMIN_SECRET)  { license_id, hardware_id } → 200
GET  /admin/list     (Bearer ADMIN_SECRET)  → [ {license_id, tier, hw, last_seen, expires} ]
```

`/activate` and `/refresh` **embed the current kill-switch decision**
in what they return, so a killed license can't get a fresh token —
see §4.

---

## 4. The kill switch (the part the user actually asked for)

Two independent levers, because "a crucial bug" and "one misbehaving
friend" are different problems:

### 4.1 Per-license revoke (one friend)

`POST /admin/revoke { license_id }` sets the KV record's
`status="revoked"`. On that license's next `/refresh` (app start, or
when the token is >7 days old), the Worker returns **410**. The client
keeps the cached token for the **7-day grace window** (design §11) and
shows a red banner, then falls back to unlicensed (1 broker). To make
revoke bite *immediately* rather than at grace-end, see §4.3.

### 4.2 Global kill switch (crucial bug — stop everyone)

`POST /admin/kill { active: true, message: "Paused: fixing a fill
bug — update coming", min_app_version: "0.8.0" }` writes
`killswitch:global`. Then:

- **`/refresh` returns 423 (Locked)** for every license while the
  switch is active (or while the app's version is below
  `min_app_version`). No new tokens are minted.
- **`/activate` refuses** too (friends can't activate around it).
- The lightweight **`GET /killswitch`** lets the app check on
  *startup* and *before placing orders* without a full refresh.

`min_app_version` is the surgical form: kill only builds ≤ the buggy
version, so friends who've updated keep running. That's the
"crucial bug in version X" case exactly.

### 4.3 How hard the kill bites — grace vs immediate

There's a real tension: the 7-day grace window (design §11) exists so
flaky home internet doesn't brick a friend mid-run, but a *crucial
bug* wants to stop trading **now**, grace be damned. Resolve it by
splitting what grace protects:

- **Tier/expiry grace stays** — a network blip never downgrades a
  friend. (Unchanged.)
- **The kill switch is NOT graced.** Add a client rule: on startup and
  **before any order placement**, the app calls `GET /killswitch`
  (cheap, cached ~60s). If `active` (and version matches), the app
  **blocks order placement immediately** — no 7-day grace — and shows
  the operator's message. Read-only actions (holdings, balances) still
  work so the friend isn't left in the dark.

This gives the operator a genuine emergency stop: flip `/admin/kill`
and the next time any friend's app tries to trade, it refuses. The
worst case (friend is fully offline and can't reach `/killswitch`) is
bounded — if you also revoke the license, the token expires at grace
end regardless; and a fully-offline friend isn't placing the buggy
trades against your server-mediated flow anyway.

> **Fail-open vs fail-closed for the pre-trade check:** default
> **fail-open on a network error** (can't reach `/killswitch` →
> allow), because bricking every friend because Cloudflare had a blip
> is worse than the rare case of a kill not reaching an offline box.
> The operator can make it fail-closed per incident by *also*
> revoking, which removes the token at grace end. Document this choice
> loudly so it's a decision, not an accident.

---

## 5. Client side — `src/license/client.py`

The one missing client file. Thin, no business logic (that's
`manager.py`'s job):

```python
# src/license/client.py  (sketch)
LICENSE_SERVER_URL = "https://rsa-license.<subdomain>.workers.dev"

def activate(license_key: str) -> tuple[bool, str]:
    """POST /activate → verify signature → token_store.save(). Returns (ok, message)."""
    hw = fingerprint.hardware_id()
    resp = _post("/activate", {
        "license_key": license_key, "hardware_id": hw,
        "hostname_hash": _hostname_hash(), "app_version": APP_VERSION,
        "platform": _platform_tag(),
    })
    # 404/409/410 → friendly message, no token written.
    token = resp.json()
    if not verify.verify_token(token, _keys.PUBLIC_KEY_B64):  # trust the sig, not the server
        return False, "Activation response failed signature check."
    token_store.save(token)
    return True, "Activated."

def refresh_if_stale() -> None:
    """Best-effort background refresh on app start when token > 7 days old.
    Network failure is swallowed — cached token keeps working (grace)."""

def killswitch_status() -> dict:
    """GET /killswitch. Cached ~60s. Fail-OPEN on network error (see §4.3)."""
```

Wiring:
- **Activation** is the wizard's Step 1
  (`docs/SIMPLE_MODE_DESIGN.md` §3) and the License section's
  "Activate with new key" button.
- **`refresh_if_stale()`** runs once on app start (non-blocking).
- **`killswitch_status()`** is checked on startup and gated into the
  **engine preflight** — the same place the license cap already gates
  (`manager.py` enforcement point #3). If killed, the preflight
  refuses to place orders with the operator's message. This composes
  with, and is stronger than, the existing tier gate.
- **Nothing outside `src/license/` imports `client.py` directly** —
  the GUI calls small `manager.py` wrappers (`activate()`,
  `is_killed()`), preserving the single-decision-site rule.

`requests` (already a dep) or `urllib` both work; keep timeouts short
(a few seconds) so a slow server never wedges startup — same
bounded-timeout discipline as the broker patches.

---

## 6. Operator CLI (`admin/rsa_license.py`)

A ~100-line wrapper over the admin endpoints so the operator never
hand-crafts curl:

```
rsa-license issue  --tier advanced --for "Alice" --expires 1y   → prints rsa-XXXX-XXXX-XXXX
rsa-license revoke <license_id>
rsa-license kill   --on  --message "Paused: fill bug, update coming" [--min-version 0.8.0]
rsa-license kill   --off
rsa-license rebind <license_id> <new_hardware_id>
rsa-license list
```

Reads `ADMIN_SECRET` from 1Password / env. `kill --on` is the big red
button; `kill --off` clears it once the fix ships.

---

## 7. End-to-end build checklist

1. `python scripts/gen_license_keys.py` → save private (1Password),
   put public in `src/license/_keys.py`.
2. `wrangler kv namespace create LICENSES`; fill `wrangler.toml`.
3. Write the Worker (`index.ts`, `sign.ts`, `kv.ts`).
4. `wrangler secret put PRIVATE_KEY_B64` / `ADMIN_SECRET`;
   `wrangler deploy`.
5. **Golden-vector test**: Worker signs a fixed payload → Python
   `verify.verify_token(...)` returns `True`. Do NOT proceed until
   green (canonicalization is the #1 failure).
6. `src/license/client.py` (activate / refresh / killswitch) +
   `LICENSE_SERVER_URL`.
7. Wire activation into the wizard + License section; wire
   `killswitch_status()` into startup + engine preflight.
8. `admin/rsa_license.py` CLI.
9. Issue yourself an **Operator** license and 1–2 alpha testers
   (design §14). Test the full loop: issue → activate → trade →
   `kill --on` → confirm the next trade is blocked → `kill --off` →
   confirm it resumes.
10. Rebuild with Nuitka (folds into the Windows installer plan); the
    public key is embedded, the private key never is.

## 8. Both forks (operator keeps pro + friend)

The license layer is **identical** in both builds — same
`src/license/`, same embedded public key, same server. The only
difference:
- **Friend build**: ships license gating ON, no bypass flag, Simple
  Mode ON.
- **Pro build**: the operator holds an **Operator-tier** license (cap
  = unlimited) or uses `RSA_LICENSE_BYPASS=1`. Same code, different
  token.

So a feature ported from pro → friend (or back) never touches the
license code — it's the same module in both. This is the same
one-codebase invariant as `docs/SIMPLE_MODE_DESIGN.md` §5: divergence
lives in build config and which token/flags are present, never in
`src/`.

## 9. Security notes / footguns

- **Trust the signature, not the server response.** `client.py`
  re-verifies every token with the embedded public key before saving.
  A compromised/rogue server still can't mint a token the app accepts
  without the private key.
- **Private key never touches the app or the repo.** Only the Worker
  (as a secret) and 1Password.
- **Rotate plan**: if the private key leaks, generate a new keypair,
  reship the app with the new public key, re-issue licenses. Painful
  but bounded — and the reason to keep the private key on as few
  machines as possible.
- **Kill switch fail-open default** (§4.3) is a deliberate
  availability choice; revoke is the fail-closed companion. Know which
  you're using per incident.
- **Rate-limit `/activate`** (Cloudflare Worker rate limiting or a
  simple per-IP KV counter) so the key space can't be probed, even
  though 80-bit keys make brute force hopeless anyway.
