# Design: Simple Mode + first-run setup wizard (Friends Edition)

Status: **proposal, not built.** Goal: a version the operator forks
for a few trusted friends that is **less to troubleshoot** — fewer
knobs, fewer failure modes, an install-and-go first run — while
staying **one codebase** so features port back and forth between the
pro build and the friend build without a divergent rewrite.

This doc is the "less robust, less debug/override" version the
operator has asked for repeatedly. It sits next to two existing docs
and does **not** duplicate them:
- `docs/WINDOWS_INSTALLER_DESIGN.md` — how the friend *gets* the app
  (Nuitka + Inno Setup, browser fetch, code-signing).
- `docs/LICENSE_TIERS_DESIGN.md` + `docs/CLOUDFLARE_LICENSE_BUILD.md`
  — the license gate / remote kill switch that governs *whether* a
  friend can run it.

Simple Mode is the **in-app experience** between those two: what the
friend sees after install and before their first trade.

---

## 1. Design principles

1. **One codebase, one runtime flag.** Simple Mode is not a fork of
   the source — it's a boolean the app reads at startup. The "friend
   fork" is the *same* repo built with `simple_mode` defaulted on and
   a curated broker set. That's what lets the operator pull a working
   feature from pro into friend (and vice-versa) with a cherry-pick,
   not a merge war. **The moment Simple Mode becomes a second
   codebase, porting dies — so it must stay a flag.**
2. **Remove decisions, not capability.** Simple Mode hides advanced
   surfaces (Diagnostics, watchdog panels, override toggles, dry-run
   internals). It does not remove the ability to place a trade or
   read balances. A friend should never see the word "sentinel,"
   "watchdog," or "reconcile."
3. **API brokers first.** The friend build ships with the
   browser-driven brokers **off by default** (Chase, Fidelity, Wells
   Fargo, SoFi) because those are where 90% of the operator's
   troubleshooting has gone (CAPTCHAs, headless Chrome, encoding,
   hangs). Friends start on the API brokers, which fail loudly and
   cheaply. (See §4.)
4. **Fail toward "ask the operator," not "improvise."** Where the pro
   build offers an override, the friend build offers a clear message
   and, if needed, a support handle — never a debug console.

## 2. The `simple_mode` flag

A single resolved boolean, same shape as the license bypass flag
(env OR sentinel file OR build default), evaluated once at startup:

```
priority (first hit wins):
  1. RSA_SIMPLE_MODE=1 / =0         env override (operator testing)
  2. creds/simple_mode.flag          sentinel file (operator toggle in GUI)
  3. build default                   friend build ships True, pro build False
```

Put it in `src/gui/core/mode.py` next to the other core helpers:

```python
def simple_mode() -> bool: ...
def set_simple_mode(*, enabled: bool) -> None:   # sentinel toggle, mirrors license bypass
```

Everything else keys off `simple_mode()`. **No feature checks the env
var directly** — one source of truth, so a future "also hide X in
simple mode" is one edit.

### 2.1 What Simple Mode hides

The GUI already uses a persistent `st.segmented_control` section
selector (`active_section`). Simple Mode filters that label list:

| Section | Pro | Simple |
|---------|-----|--------|
| Trade | ✅ | ✅ |
| Balances | ✅ | ✅ |
| Status | ✅ | ✅ (slimmed — plain "running / done / error") |
| Credentials | ✅ | ✅ (curated broker list, §4) |
| Trade-beta | ✅ | ❌ hidden |
| Ledger | ✅ | ❌ hidden (reset-by-ticker stays reachable via a small "Trouble with a stock?" link) |
| Diagnostics / render-hang | ✅ | ❌ hidden entirely |
| Errors & Troubleshooting | ✅ | ✅ but reduced to plain-language guidance, no logs dump |
| License | ✅ | ✅ (activation only — see §6) |

Advanced sidebar toggles (Chase auto-limit, diagnostic screenshots,
watchdog, bypass) are hidden in Simple Mode and take their safe
defaults. The friend can't turn on `RSA_FIDELITY_DIAGNOSTIC`, can't
disable the after-hours limit, can't flip XSRF — they get the
operator's chosen-good defaults.

### 2.2 What Simple Mode changes (not just hides)

- **Status** collapses the per-broker timeline into one line per
  broker: ⏳ running / ✅ done / ⚠️ needs attention. No stuck-on-X
  internals.
- **Errors** map raw failures to friend-language. A `charmap`
  traceback the friend must never see; it becomes "Couldn't reach
  this broker — try again, and if it keeps happening, message
  <operator>." The mapping table lives in one dict so pro keeps the
  raw detail and friend gets the plain version from the same source.
- **Trade** defaults to the simplest path (market-ish, single amount)
  and hides the beta trade panel.

## 3. First-run setup wizard

The install doc gets the *binary* onto the machine and fetches
browsers. The wizard is what runs the **first time the GUI opens** and
walks a non-dev from "blank app" to "first successful trade" without a
terminal. It's a gated linear flow (a `wizard_step` in session state)
shown only until completed (a `creds/setup_complete.flag` marks done):

```
Step 0  Welcome            "This tool places the same order across your brokers."
Step 1  Activate license   paste license key → activate (Cloudflare, see build guide).
                           Until activated, only 1 broker is allowed (unlicensed cap).
Step 2  Create your vault   choose a master password → creates creds/vault.json.
                           Plain-language: "This password encrypts your broker
                           logins on THIS computer. We never see it."
Step 3  Add a broker        curated API-broker picker (§4). One broker to start.
                           Inline "test connection" that pulls holdings so the
                           friend sees it work before trusting it with an order.
Step 4  Dry run             a forced paper/dry trade so the friend watches the
                           flow end-to-end with zero risk.
Step 5  Done                "You're set. Add more brokers any time in Credentials."
```

Design notes:
- **Prerequisite install belongs to the installer, not the wizard**
  (§3 of the Windows doc: first-run browser fetch). The wizard assumes
  a working runtime; it only does *user* setup (license, vault,
  broker, dry run). If a browser broker is later enabled and its
  engine is missing, that's surfaced as a one-click "Install the
  browser component" action, not a wizard step everyone sees.
- **The wizard is Simple-Mode-aware but not Simple-Mode-only.** The
  pro build can run it too (skippable). Keeps it one code path.
- **Every step is resumable.** Closing the app mid-wizard reopens at
  the same step; nothing half-written. Vault creation and license
  activation are each idempotent.
- **Test-before-trust.** Steps 3 and 4 (pull holdings, then dry run)
  exist specifically so a friend's first *real* order isn't also the
  first time anything talked to the broker.

## 4. Curated API-broker set

The friend build's default Credentials list is the **non-browser**
brokers, because those are the low-troubleshooting ones. From
`brokers_meta.py` (`browser_based` flag):

**Friend default (API / library-driven):**
BBAE, DSPAC, Fennel, Public, Robinhood, Schwab, Webull.

**Hidden by default in the friend build (browser-driven):**
Chase, Fidelity, Wells Fargo, SoFi — each needs system Chrome /
Playwright / nodriver, hits CAPTCHAs and 2FA, and is where the
operator's debugging time actually goes.

Mechanism: `brokers_meta.py` already carries `browser_based`. Add a
`friend_default: bool` (or simply "in Simple Mode, list
`browser_based=False` brokers first and collapse browser brokers
behind an 'Advanced brokers (needs extra setup)' expander"). The
operator can still enable a browser broker for a friend by flipping
the expander — nothing is *removed*, just de-emphasized and
un-defaulted. Combined with the license cap (unlicensed = 1 broker),
a new friend's happy path is: activate → add one API broker → trade.

This also dovetails with `docs/FILL_VERIFICATION_DESIGN.md`: API
brokers are exactly the ones with real order-status endpoints, so a
friend's trades get **strong inline fill verification**, while the
troublesome browser brokers (weak inline verification) are the ones
they're steered away from. The two designs reinforce each other.

## 5. Fork strategy — keeping both builds in sync

The operator wants to keep BOTH forks and move features between them.
Recommended, in order of preference:

1. **Same repo, two build profiles (best).** No fork at all. A
   `build/profile.py` (or a Nuitka `--include-data` constant) sets the
   `simple_mode` and broker-curation defaults at build time. Pro and
   friend are the *same* commit built twice. Feature work lands once;
   both builds get it. This is the whole reason Simple Mode is a flag.
2. **Long-lived `friend` branch (acceptable).** If a separate repo is
   required for distribution hygiene, keep `friend` as a branch that
   only ever differs by the build profile + shipped defaults, and
   merge `main` → `friend` regularly. Never let application logic
   diverge between them — divergence there is what kills porting.
3. **Separate repo (avoid).** Only if distribution/legal forces it.
   Then the friend repo is a *thin* overlay: build config + a pinned
   pointer to the pro repo as a submodule/vendored source, never a
   hand-edited copy of `src/`.

Whichever is chosen, the invariant is: **`src/` is identical between
the two.** All divergence lives in build config + the runtime flag.

## 6. License integration

Simple Mode and the license gate are orthogonal but complementary:
- The friend build ships with Simple Mode **on** and license gating
  **on** (no operator bypass flag present).
- The wizard's Step 1 is the activation flow from
  `docs/CLOUDFLARE_LICENSE_BUILD.md`. Until activated, the unlicensed
  cap (1 broker) applies — which is *fine* for the "try one broker"
  onboarding and doubles as a gentle nudge to activate.
- If the operator later needs to **stop a friend** (crucial bug), the
  remote revoke / global kill switch in the Cloudflare build guide
  takes effect on next refresh, and Simple Mode's Errors panel shows
  the friend a plain "This app is paused by the operator — check your
  messages" rather than a raw failure.

## 7. Build sequencing

1. `src/gui/core/mode.py` — `simple_mode()` / `set_simple_mode()`
   (mirror the license-bypass flag exactly) + tests.
2. Gate the `active_section` label list and sidebar toggles on
   `simple_mode()`. Pro behavior unchanged when the flag is off.
3. Error-message mapping dict (raw → friend-language) with pro
   showing raw, friend showing mapped.
4. Broker curation: order/collapse browser brokers behind an
   "Advanced brokers" expander in Simple Mode.
5. First-run wizard (`wizard_step` state machine + `setup_complete`
   sentinel), steps 0–5, resumable, idempotent.
6. Build profile (`build/profile.py`) wiring the friend defaults;
   fold into the Nuitka build from the Windows installer doc.
7. Soak: operator runs the friend build themselves with Simple Mode
   on for a week before handing it to anyone.

## 8. Tests

- `simple_mode()` resolution order (env > sentinel > default), all
  branches.
- Section list excludes the hidden sections when the flag is on,
  includes them when off — using the AppTest harness (remember it
  only renders the active section; set `active_section` per assertion,
  same fix used after the segmented-control change).
- Error mapping: a known raw failure (e.g. the Chase `charmap`
  traceback) maps to the friend-language string; unknown failures
  fall back to a generic safe message, never a traceback.
- Broker curation: browser brokers are not in the default-visible set
  in Simple Mode; are reachable via the expander.
- Wizard state machine: resumes at the right step; `setup_complete`
  sentinel ends it; each step idempotent (re-running vault create /
  activation doesn't corrupt state).

## 9. What we deliberately do NOT do

- No separate "friend" source tree. One `src/`, always.
- No feature that exists *only* in the friend build. If it's worth
  building, it's behind the flag in the shared code.
- No telemetry on friends beyond what the license layer already does
  (activation/refresh). Simple Mode watches nothing.
- No auto-enabling browser brokers for a friend without the operator
  explicitly turning them on.
