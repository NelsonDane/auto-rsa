# Design: fill verification (did the order ACTUALLY fill?)

Status: **proposal, not built.** Goal: close the gap the Chase
queue-eligible bug exposed — the engine reported 8 orders "placed"
that never reached the broker. We already guard that specific case
(`_chase_direct_order.py` refuses to record a queue-eligible response
as a fill), but that was one broker, one symptom. This spec makes
"did it actually fill?" a **first-class, per-broker capability** so a
silent non-fill can't be reported as success anywhere.

---

## 1. The problem, precisely

There are three distinct states a broker order can be in, and today
the code collapses them into two ("success" / "failure"):

| State | What the broker told us | What we should record |
|-------|-------------------------|------------------------|
| **Filled** | order executed, shares/cash moved | success ✅ |
| **Accepted-but-pending** | queued / working / after-hours eligible | *not filled yet* — pending ⏳ |
| **Rejected / never-placed** | validation failed, or no order id returned | failure ❌ |

The Chase bug was the middle row leaking into the top row:
`orderQueueAvailabilityIndicator: True` means **eligible to queue**,
not **filled**, and the old code read a non-empty response as a fill.
The user checked all Chase accounts and the orders were absent.

Two things need to exist for this class of bug to be structurally
impossible:

1. **Inline verification** — at placement time, distinguish
   filled / pending / rejected from the broker's *own* response, and
   never let "pending" or "eligible" masquerade as "filled."
2. **Post-hoc reconciliation** — after the run, cross-check the
   ledger against broker reality. This already exists
   (`src/gui/core/reconcile.py`) but is **holdings-based** and
   **quantity-blind** (see §4); it needs a fill-aware upgrade.

## 2. What we already have (don't rebuild it)

- `src/gui/core/reconcile.py` — compares ledger buy rows against a
  holdings snapshot at **broker+ticker** granularity. Verdicts:
  `MISSING` (ledger says EXECUTED, share not held → silent failure),
  `REVIEW_FILLED` / `REVIEW_MISSED` (resolves an ambiguous
  NEEDS_REVIEW), `STALE`, `UNVERIFIABLE`, `ORPHAN`, `OK`. Pure logic,
  fully unit-tested. **This stays** — it's the backstop.
- `src/ledger.py` — the execution ledger, with `STATUS_INTENDED`,
  `STATUS_EXECUTED`, `STATUS_FAILED`, `STATUS_NEEDS_REVIEW`. Intent
  is recorded *before* the order is placed (double-buy guard), so a
  break mid-place lands in NEEDS_REVIEW, not FAILED.
- The `order-reconciler` subagent — a read-only operator tool that
  cross-checks ledger vs holdings + trade history on demand.
- Chase's inline guard — the proof-of-concept for layer 1, but
  bespoke to Chase.

The job here is to (a) generalize the Chase inline guard into a
broker capability and (b) make reconciliation quantity-aware and,
where the broker supports it, order-status-aware rather than
holdings-only.

## 3. Layer 1 — inline fill verification at placement

### 3.1 A verdict type every broker returns

Today each `broker_api.py` prints free-text and the engine scrapes it.
Introduce a small structured result the order path can attach to the
ledger, without ripping out the existing print-based flow:

```python
# src/brokerages/fill_result.py
from enum import Enum
from typing import NamedTuple

class FillState(str, Enum):
    FILLED    = "filled"      # shares/cash actually moved
    PENDING   = "pending"     # accepted, queued, working, after-hours eligible
    REJECTED  = "rejected"    # validation failed / broker refused
    UNKNOWN   = "unknown"     # no authoritative signal — treat as NOT filled

class FillResult(NamedTuple):
    state: FillState
    broker: str
    account: str
    ticker: str
    action: str
    qty: float | None          # filled qty if the broker reports it
    order_ref: str | None      # broker order id, for later status polling
    detail: str = ""           # human-safe explanation
```

The rule that makes the Chase bug impossible everywhere:

> **Only `FillState.FILLED` may mark a ledger row EXECUTED.**
> `PENDING` → a new `STATUS_PENDING` row. `REJECTED` → FAILED.
> `UNKNOWN` → NEEDS_REVIEW (ambiguous, blocks re-fire).

`mark_result(success=True/False)` is too coarse for this — it can't
express "pending." Add `ledger.mark_fill(play, result: FillResult)`
that maps the four states to statuses in one place, and keep
`mark_result` as a thin wrapper (`success=True` → FILLED,
`success=False` → FAILED) so existing call sites don't break.

### 3.2 Per-broker `classify_fill()` — feasibility matrix

Each broker interprets its own response. The honest per-broker
picture (what the underlying API/flow actually exposes):

| Broker | Order id? | Status/fills query? | Inline verdict source |
|--------|-----------|---------------------|------------------------|
| Chase (direct API) | yes | yes (`/orders`, order detail) | **already done** — queue-eligible → PENDING, filled → FILLED |
| Robinhood (`robin_stocks`) | yes | yes (`get_stock_order_info`) | poll order id → `state` field (`filled`/`confirmed`/`queued`/`rejected`) |
| Schwab (`schwab-api`) | yes | yes (order status endpoint) | poll order id → status enum |
| Webull (`webull`) | yes | yes (`get_order`) | poll order id → status |
| Public | yes | partial | response `status`; fall back to reconcile |
| Fennel | yes | partial | GraphQL order state if present; else reconcile |
| BBAE / DSPAC | limited | limited | response body flag; else reconcile |
| Fidelity (browser) | no clean id | scrape confirmation | confirmation-page text = FILLED/REJECTED; no reliable pending state → reconcile is primary |
| Wells Fargo (browser) | no clean id | scrape | confirmation text; reconcile primary |
| SoFi (browser) | no clean id | scrape | confirmation text; reconcile primary |

Design consequence: **API brokers get strong inline verification;
browser brokers lean on layer 2.** This is also why the Friends
Edition starts on API brokers (see `docs/SIMPLE_MODE_DESIGN.md`) —
they're the ones where "did it fill?" is answerable in-band.

Each broker module gains an optional:

```python
def classify_fill(place_response, *, broker, account, ticker, action) -> FillResult:
    ...
```

Brokers that can't answer inline return `FillState.UNKNOWN` (→
NEEDS_REVIEW, and layer 2 resolves it). No broker is *required* to
implement it; absence = UNKNOWN. This keeps the rollout incremental:
Chase first (already effectively there), then Robinhood/Schwab/Webull
(clean order-status APIs), browsers last.

### 3.3 Optional short poll for pending orders

For API brokers with a status endpoint, an order that comes back
`PENDING` during market hours can be polled a few times (bounded:
e.g. 3 tries × 2s) to see if it flips to `FILLED` before the run ends.
After-hours or still-pending after the poll budget stays PENDING —
**never** upgraded to FILLED without an authoritative fill. The poll
is best-effort and time-boxed so it can't wedge a run (same
discipline as the Chase request-timeout patch).

## 4. Layer 2 — quantity-aware reconciliation

The current `reconcile()` treats holdings as a **set**: "is TSLL held
at Chase?" That has two blind spots the fill-verification work must
close:

1. **Re-buying a held symbol.** If the account already holds TSLL and
   we buy one more share, set-membership says "held" → `OK`, even if
   the new order silently failed. The share count didn't go up, but
   we can't see that.
2. **Partial fills.** Ordered 5, filled 2 — set membership says
   "held," reconciliation says `OK`, and the 3-share shortfall is
   invisible.

### 4.1 Quantity delta

Extend the holdings snapshot to carry **per-broker+ticker quantity**
(the holdings capture already reads share counts; today they're
dropped at reconcile time). Then a buy row can be checked as:

```
expected_qty_after = qty_before + ordered_qty
verdict = OK        if held_qty >= expected_qty_after (within a small epsilon)
        = SHORTFALL  if qty_before < held_qty < expected_qty_after   (partial)
        = MISSING    if held_qty <= qty_before                        (nothing landed)
```

This needs a **before** snapshot. Two options, cheapest first:
- **Use the prior run's captured holdings as `qty_before`.** We
  already persist holdings per broker with a `captured_at`. If the
  last capture predates this order and a fresh capture postdates it,
  the delta is meaningful. No new capture needed most of the time.
- **Opportunistic pre-capture** for API brokers (cheap): snapshot the
  one symbol's qty right before placing. Skipped for browser brokers
  (too slow).

Keep the set-based path as the fallback when quantities aren't
available (browser brokers, stale snapshots) — degrade to today's
`OK`/`MISSING`, never worse.

### 4.2 Order-history cross-check (where available)

For brokers exposing recent-orders/trade-history (Chase, Robinhood,
Schwab, Webull), reconciliation can additionally confirm a matching
**filled** order exists in the broker's own history for the ticker on
the run date — the strongest possible signal, independent of holdings
math. This is what the `order-reconciler` agent does by hand today;
the spec is to make it a code path the GUI can run, not just an agent.

## 5. Ledger schema additions

Additive, migration-safe (new nullable columns; old rows read fine):

```
order_ref     TEXT     -- broker order id (for status polling / audit)
fill_state    TEXT     -- last known FillState (filled/pending/rejected/unknown)
filled_qty    REAL     -- quantity actually filled (NULL if unknown)
verified_at   TEXT     -- ISO ts of the last verification (inline or reconcile)
verify_source TEXT     -- 'inline' | 'poll' | 'reconcile-qty' | 'reconcile-history'
```

Add `STATUS_PENDING` to the status enum. State machine:

```
INTENDED ──place──> FILLED        (authoritative fill)
                └──> PENDING       (accepted, not yet filled)  ──verify──> FILLED / FAILED
                └──> FAILED        (rejected / never placed)
                └──> NEEDS_REVIEW  (ambiguous / UNKNOWN)        ──reconcile──> resolved
```

PENDING is **not** a terminal success. A PENDING row that never
resolves to FILLED by end-of-run surfaces in the GUI as "placed but
unconfirmed — verify at the broker," and — critically — is **not**
counted as done for double-buy purposes in a way that would let a
retry re-place it (same conservatism as NEEDS_REVIEW).

## 6. GUI surfacing

Build on the existing Diagnostics / reconciliation panel and the
per-run progress:

- **Per-run summary line**: `✅ 6 filled · ⏳ 2 pending · ❌ 1 rejected`
  instead of a flat "8 placed." A non-zero pending/rejected count is
  the honest headline the Chase run should have shown.
- **Reconciliation panel** gains `SHORTFALL` (🟠 partial fill) and
  keeps `MISSING`/`REVIEW_*`. Each row shows expected vs held qty when
  known.
- **Pending tray**: PENDING rows with a "Re-check now" button that
  re-polls the order id (API brokers) or prompts a fresh holdings
  pull (browser brokers).
- A run-progress sentinel `FILL\t<broker>\t<ticker>\t<state>` so the
  activity bar reflects fills in real time, mirroring the existing
  sentinel pattern.

## 7. Why this is the right shape

- **Fail safe, not fail silent.** Every ambiguity resolves toward
  "not filled / needs review," never "filled." That's the exact
  inversion of the Chase bug.
- **Incremental.** UNKNOWN is a valid answer, so a broker with no
  status API loses nothing — it just relies on layer 2, same as
  today. Chase is already done; Robinhood/Schwab/Webull are the
  high-value next steps because they have clean order-status APIs.
- **One decision site.** `ledger.mark_fill()` is the only place a
  FillState becomes a status, the same "single source of truth"
  discipline as `license/manager.py` and `tiers.py`.
- **Reuses proven machinery.** Holdings capture, the reconcile
  module, the sentinel protocol, and the bounded-timeout discipline
  all already exist; this composes them rather than adding a new
  subsystem.

## 8. Tests

- **State mapping**: each `FillState` → exactly the right ledger
  status via `mark_fill` (FILLED→EXECUTED, PENDING→PENDING,
  REJECTED→FAILED, UNKNOWN→NEEDS_REVIEW).
- **Chase queue-eligible regression** (already have one for the
  direct path) re-expressed through `classify_fill` → PENDING, and
  asserts it can NEVER become EXECUTED without a fill.
- **Quantity delta**: qty_before=1, ordered=1, held_after=1 →
  MISSING (re-buy of a held symbol that didn't land); held_after=2 →
  OK; held_after between → SHORTFALL.
- **Partial fill**: ordered 5, filled 2 → SHORTFALL with the right
  numbers in the note.
- **Pending never upgrades without a fill**: a PENDING row left
  unresolved stays PENDING and blocks a naive re-fire.
- **Degrade path**: no quantities available → falls back to the
  existing set-based OK/MISSING (no regression to reconcile.py's
  current tests).

## 9. Build sequencing

1. `fill_result.py` + `ledger.mark_fill()` + `STATUS_PENDING` +
   schema columns + mapping tests. (In-repo, no broker changes.)
2. Re-express the **Chase** inline guard as `classify_fill` returning
   FILLED/PENDING/REJECTED (behavior-preserving; it already does the
   hard part).
3. **Robinhood** `classify_fill` via `get_stock_order_info` order
   state (highest-value browser-free win after Chase).
4. Quantity-aware reconcile: carry qty through the snapshot, add
   `SHORTFALL`, keep set-based fallback.
5. Schwab + Webull `classify_fill`.
6. GUI: fill summary line, pending tray, reconcile SHORTFALL row.
7. Order-history cross-check as a GUI-runnable code path (fold in the
   `order-reconciler` agent's logic).

Steps 1–3 alone would have caught the Chase incident honestly and
are the minimum viable slice; the rest hardens breadth.
