# Design: persistent broker sessions (FOR REVIEW)

Status: **scoping, not built.** Goal: let an unattended scheduler avoid
re-doing 2FA on every run by reusing a prior approved session — exactly
the behavior you saw in the Discord version ("once approved, only
needed occasionally after"). That occasional re-prompt is the broker's
*device-trust cookie* aging out; persistence works when we (a) reuse
the session artifact and (b) the broker remembered the device.

## 1. The key reframe

Unattended 2FA is **not a universal blocker**. The per-broker survey
shows most API-library brokers *already* persist a token/pickle in
`creds/` and re-login silently. So the auto-executor (M5) can start
**today** with those brokers and add browser brokers incrementally.

`creds/.gitignore` ignores everything but itself, so every session
artifact below is already safe from git. On the Mac Mini these files
are **credential-equivalent** (a valid session = account access) —
this is the core argument for **FileVault On** and `chmod 600`.

## 2. Per-broker reality (from code survey, with anchors)

### Tier 1 — already unattended-ready (no code change)
| Broker | Mechanism | Anchor |
|---|---|---|
| Robinhood | pickle token cache (30-day) | `robinhood_api.py:44-51`; vendor `robin_stocks/.../authentication.py:156-165` |
| Schwab | `session_cache=./creds/schwab{n}.json` | `schwab_api.py:39` |
| BBAE | `./creds/BBAE_{n}.pkl` | `bbae_api.py:29-34` |
| DSPAC | `./creds/DSPAC_{n}.pkl` | `dspac_api.py:29-34` |
| Fennel | PAT token (no session needed) | `fennel_api.py:42` |
| Public | API key (no session needed) | `public_api.py:48` |
| Tradier | bearer token (no session needed) | `tradier_api.py:80` |

These re-auth silently as long as the cached token/key is valid; a
stale token falls back to the normal (interactive) login.

### Tier 2 — Fidelity: small wiring (priority)
- The patchright patch already writes a Playwright `storage_state`
  JSON at `./creds/Fidelity_{title}.json`
  (`_fidelity_patchright.py:40-46, 62`).
- **Missing:** on a later run, load that storage_state into the
  context and **skip the `login_2FA()` call when the session is still
  valid** (2FA trigger `fidelity_api.py:133-143`).
- Effort: low. Highest value (Fidelity is the unattended priority).

### Tier 3 — Chase / Vanguard: profile reuse
- Both create a browser profile dir under `./creds` but recreate it
  per run (`chase_api.py:149-154`, `vanguard_api.py:60`). Chase already
  has a stale-profile cleanup at `chase_api.py:28-58`.
- **Missing:** detect a valid prior profile and reuse it instead of a
  fresh login. Medium effort.

### Tier 4 — Firstrade / SoFi: nearly there
- Firstrade has a `profile_path="./creds/"` (`firstrade_api.py:43`) —
  reuse + skip 2FA when present.
- SoFi already *saves* a cookie pickle (`sofi_api.py:147`) and has a
  `_load_cookies_from_pkl()` (`sofi_api.py:59-69`) that is **defined
  but never called before login** — wiring that call in is the whole
  fix. Low effort, isolated.

### Tier 5 — Wells Fargo / Tornado: no persistence
- Vanilla Selenium via `get_selenium_driver()` with **no
  user-data-dir** (`helper_api.py:460-499`). Fresh browser, 2FA every
  run. Needs a persistent `--user-data-dir` per broker/account. Medium
  effort but touches a shared helper.

### Tier 6 — Tastytrade / Webull: refactor
- Tastytrade `Session` token is in memory only (`tasty_api.py:57-61`) —
  would need to serialize token+expiry to disk and reload.
- Webull caches only a device-id pickle, not credentials — needs a new
  session layer. Highest effort; defer.

## 3. Design principles (apply to every tier we wire)

1. **Reuse, verify, fall back.** On init: if a session artifact exists
   and a cheap liveness probe passes (e.g., load an authed page /
   account list without a login redirect), use it and **skip 2FA**.
   If the probe fails or the artifact is missing/stale, fall back to
   the *existing* interactive login unchanged.
2. **Never silently trade on a broken session.** A failed liveness
   probe must downgrade to login, not proceed unauthenticated.
3. **Staleness budget.** Treat artifacts older than a per-broker TTL
   (start conservative, e.g. 5–7 days) as stale → re-auth. Cheaper to
   re-2FA occasionally than to hang a headless run.
4. **One artifact per (broker, account/parent).** Keying mirrors the
   existing naming (`Fidelity_{title}.json`, `schwab{n}.json`, …).
5. **No behavior change when unattended is off.** Reuse is additive;
   manual GUI runs keep prompting exactly as today.
6. **Security:** artifacts are credential-equivalent → `creds/` only
   (already gitignored), `chmod 600`, FileVault On on the host, and the
   re-2FA path still routes its prompt to the GUI/Discord for
   attended runs.

## 4. Re-auth fallback for unattended runs

Headless can't answer a fresh OTP. Strategy, in priority order:
1. **Session reuse within TTL** (this design) — the common path.
2. **TOTP auto-answer** where the broker supports an authenticator
   secret (we already depend on `pyotp`; Schwab's lib already does this
   internally). **Decision (locked): Fidelity uses TOTP** — the account
   now has an authenticator secret, so Fidelity's unattended re-auth is
   self-healing (generate the code with `pyotp` and feed it where
   `login_2FA()` currently reads `input()` /
   `get_otp_from_discord`, `fidelity_api.py:133-143`). This means
   Fidelity does **not** depend on the storage_state TTL for
   unattended operation — storage_state still helps skip the prompt
   when valid, TOTP covers every re-prompt. Build task must verify
   `fidelity-api`'s 2FA entry accepts a programmatic code and that the
   TOTP secret has a vault field.
3. **Escalate, don't guess.** If reuse fails and no TOTP is possible,
   the unattended executor **skips that broker for this run and
   alerts** (per the auto-executor failure matrix) and flips the
   broker's health indicator (§8) — it must never block on `input()`.

## 5. How it plugs into M5 (auto-executor)

- M5's `RSA_AUTO_BROKERS` allowlist starts as **Tier-1 only**
  (**locked** — Robinhood/Schwab/BBAE/DSPAC + token-only
  Fennel/Public/Tradier). They need no new code, so phase-1 shadow +
  early live can begin without any session work.
- Add **Fidelity (Tier 2)** next via the **TOTP path** (above) — the
  highest-leverage task to unblock the priority broker unattended.
- Tiers 3–5 are added one at a time, each gated by an attended dry run
  proving "reuse worked, no 2FA, correct account list."
- The headless engine path sets `RSA_UNATTENDED=1` so brokers choose
  *escalate-and-skip* instead of blocking `input()` on a failed probe.

## 6. Build phases (when approved)

1. **Audit harness:** a read-only `--check-sessions` that, per
   configured broker, reports artifact present? age vs TTL? liveness
   probe pass? — no trading. Feeds the §8 health indicator.
2. **Fidelity TOTP unattended auth** + storage_state reuse + attended
   verification (confirm a second run needs no human and lists all
   accounts).
3. **SoFi load-cookie wiring** (one call) + Tier-3 profile reuse.
4. **Selenium user-data-dir** for Wells Fargo/Tornado.
5. Tastytrade/Webull only if needed.

## 7. Decisions (locked) + remaining verification

**Locked:**
1. **TTL:** start at **5–7 days**, **configurable** —
   `RSA_SESSION_TTL_DAYS` global default plus an optional per-broker
   override map (`RSA_SESSION_TTL_OVERRIDES` JSON). Conservative by
   default: re-auth occasionally beats a hung headless run.
2. **First unattended set:** **Tier-1 only** for M5 phase-1.
3. **Fidelity:** **TOTP auto-answer** (secret added on the account) —
   not periodic attended re-login.
4. **Liveness:** surfaced as a **session-health indicator** (§8).

**Still to verify (no decision needed, just validation work):**
- [ ] M1 live-validated (gates real unattended trading).
- [ ] Tier-1 cached tokens survive Mac-Mini reboots / FileVault unlock
      — proven by the phase-1 audit harness.
- [x] **DONE — Fidelity TOTP.** Verified the vendored `fidelity-api`
      already runs the full TOTP flow internally (`pyotp`) when a
      `totp_secret` is supplied, and the GUI/vault Fidelity schema
      already has a `totp_secret` field (`empty_value="NA"`). Creds
      assemble as `user:pass:totp` and `fidelity_init` already passes
      the 3rd segment — so no SMS/Discord/`input()` when TOTP is set.
      Added the only missing piece: an unattended guard
      (`RSA_UNATTENDED=1`) so a missing-TOTP Fidelity fails fast with
      an actionable message instead of a hung `input()`; the executor
      treats it as a failed login → skip+alert. Attended path
      unchanged. Covered by `edgar_tests/fidelity_totp_test.py`.
- [ ] Per-browser-broker liveness-probe selector (one quick attended
      observation each) — only needed as we reach Tiers 2–5.

## 8. Session-health dashboard + outcome reason codes

**Two independent dimensions — do not conflate them** (operator
experience: tickers are routinely unavailable/restricted on a given
broker even when the session is perfectly fine; "no recent buys" is
normal, not breakage):

### 8a. Session health — LIVENESS only
Per (broker, artifact), a traffic light driven **purely by session
liveness vs TTL**:
- **🟢 Green** — session artifact present and fresh (< 70% of TTL); or
  a stateless token broker (no session file needed).
- **🟡 Yellow** — artifact approaching TTL (refresh soon).
- **🔴 Red** — no artifact / past TTL → re-auth (login+2FA) needed;
  the auto-executor skips this broker and alerts.
- **⚪ Unsupported / ❔ Unknown** — broker keeps no session
  (Selenium WF/Tornado) / artifact path not yet confirmed.

Trading activity is **NOT** a health input. (Earlier draft tied yellow
to "no confirmed buy in N days" — *removed*: it would false-alarm
exactly when a broker simply had no purchasable plays.) Built:
`src/session_state.py`, `python -m src.session_audit`, GUI Status
panel; TTL via `RSA_SESSION_TTL_DAYS` + override map. Real network
liveness probes are a later phase (need attended per-broker selectors).

### 8b. Outcome reason codes — explains "why no trade"
The Discord build alerted "stock unavailable for purchase"; this
restores and generalizes that. Every order result is classified
(`src/outcomes.py`, persisted on the ledger row's `reason`):
`OK, FILTERED, LEDGER_SKIP, STOCK_UNAVAILABLE, RESTRICTED, NO_FUNDS,
MARKET_CLOSED, PRICE_REJECTED, SESSION_ERROR, OTHER`.
- `is_session_problem` → only `SESSION_ERROR` (alarms; can affect the
  §8a light / trigger an alert).
- `is_benign_no_trade` → FILTERED / LEDGER_SKIP / STOCK_UNAVAILABLE /
  RESTRICTED / MARKET_CLOSED — connection was fine, expected, never an
  alarm.

The auto-executor uses these to decide skip-and-move-on (benign) vs
skip-broker-and-alert (session problem), and to NOT degrade a healthy
session for benign non-fills.

### 8c. Optional: per-play availability tracker (idea, not required)
Because `reason` is now on every ledger row, a **stock-availability
matrix** is a cheap read-only view: per (play × broker) show 🟢 if a
buy succeeded, 🔴 if `STOCK_UNAVAILABLE/RESTRICTED`, ⚪ if filtered/
already-done, from logs/ledger alone. No new tracking — just a
grouping over `ledger.list_executions()`. Scoped here; build on
request.

Mechanics (8a): snapshot persisted to gitignored `creds/sessions.db`;
written by the audit harness / every login / the executor; surfaced in
the GUI with a webhook alert on any →🔴 transition.

Nothing here changes current behavior; it is purely additive reuse with
a strict fall-back to today's interactive login.
