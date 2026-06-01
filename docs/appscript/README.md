# Apps Script — RSA Scraper patch set (v2.1 → v2.2)

These are **surgical, copy‑paste patches** for the existing
Reverse‑Split Automation Apps Script. They are intentionally *not* a
full rewrite — your script "works reliably," so each change is a
named function to **REPLACE** or **ADD**, applied in order. Test with
`CONFIG.TEST_MODE = true` before going live.

Apply the blocks in `reverse_split_patches.gs` top‑to‑bottom:

1. **EDIT `runImportCore_`** — remove the `runManualOverrides()` call
   from inside the per‑item loop (it re‑posts the whole MANUAL_QUEUE on
   every item → duplicates + 6‑min timeout → silent missed alerts) and
   call it once after the loop.
2. **ADD** `urlCacheKey_` and **REPLACE** the two cache‑key lines in
   `getCachedSecFilingText_` / `getCachedArticleText_` — fixes
   long‑URL collisions returning the *wrong filing's* cached body
   (wrong fractional policy).
3. **ADD** SEC EFTS full‑text feed (`fetchAndParseSecEFTS_`) + two
   `CONFIG.FEEDS` entries — restores authoritative 8‑K detection
   (the dead `sec_daily_index` 403s from Apps Script).
4. **REPLACE** `parseReverseSplit_` ratio block — only accept reverse
   ratios (1‑for‑N, N≥2); stops forward splits ("2‑for‑1") becoming
   false BUY signals. Also adds more effective‑date formats.
5. **REPLACE** `parseTickerGeneric_` — drops the unsafe bare `(ABCD)`
   fallback and adds a stop‑list, so `(USA)`/`(CEO)` can't become a
   `!rsa buy` target.
6. **ADD** `postFeedHealthAlert_` + one call in `runImportCore_` —
   logs a health line every run; Discord-pings **only on a real
   outage** (all feeds down / nothing fetched), throttled to ≤1 per
   12h. `CONFIG.HEALTH_ALERTS = false` silences Discord entirely.
   (v2.2.2: no longer spams when a couple of feeds transiently fail.)
7. **ADD** `isImminent_` and a one‑line tweak in
   `formatDiscordRSASignal_` — flags 🔴 URGENT when the pre‑split
   buy deadline is today/tomorrow.
8. **ADD** `writeGuiQueue_` + one call — the **GUI integration
   contract**: writes qualifying signals to a `GUI_QUEUE` sheet the
   local GUI scheduler will consume (no Discord needed).

## GUI_QUEUE contract (Phase 4 keystone)

`writeGuiQueue_` appends to a sheet named **GUI_QUEUE** with columns:

| Col | Field | Meaning |
|---|---|---|
| A | CREATED_AT | timestamp written |
| B | TICKER | symbol to act on |
| C | ACTION | `buy` (pre‑split) — `sell` added in Phase 4 exit logic |
| D | RATIO | e.g. `1-for-40` |
| E | EFFECTIVE_DATE | parsed effective date (or blank) |
| F | PRESPLIT_DEADLINE | last buy time (prev market day, 4pm ET) |
| G | FRACTIONAL_POLICY | ROUND_UP / CASH_IN_LIEU / … |
| H | CONFIDENCE | 0–1 |
| I | SOURCE | feed label / type |
| J | KEY | dedupe key (matches ANNOUNCEMENTS.KEY) |
| K | STATUS | `PENDING` — the GUI writes back `EXECUTED`/`FAILED`/`SKIPPED` |

The GUI polls this sheet (Google Sheets API or a published CSV),
dry‑run‑previews, requires the LIVE‑confirm gate, executes before
`PRESPLIT_DEADLINE`, and writes column K back. That is the entire
detect→execute pipeline with Discord removed.

## v2.2.1 — paginated EFTS

`reverse_split_efts_paginated.gs` is a drop-in replacement for
`fetchAndParseSecEFTS_` that pages through EFTS results (10/page, up to
100 filings/query, deduped by filing id, stops at the real total).
Fixes the v2.2 limitation where only the first ~10 reverse-split 8-Ks
in the window were seen. Same signature/return contract — just swap
the function body.

## v2.3 — signal types (Phase 5/6)

`phase5_signal_types.gs` extends the script to detect TWO new event
classes alongside the existing reverse-split flow:

- **Spin-offs** — `parseSpinOff_(text)` flags filings announcing a
  subsidiary distribution (SEC 8-K, S-1, S-4, Form 10). Returns
  `{matched, confidence, recordDate, distRatio, evidence}`.
- **Special dividends** — `parseSpecialDividend_(text)` flags
  one-time cash distributions (SEC 8-K Item 8.01). Returns
  `{matched, confidence, amountPerShare, exDate, recordDate,
  paymentDate, evidence}`.

Both are conservative ports of the Python classifiers in
`src/edgar/classify.py` (parse_spin_off / parse_special_dividend) and
share the same confidence floor (0.75). False positives cost more than
misses here — strong trigger phrases AND supporting context required.

Companion changes:
- **REPLACE** `writeGuiQueue_` with the version in `phase5_signal_types.gs`
  — adds a 12th column **SIGNAL_TYPE** and accepts `r.signalType`
  per emitted row (defaults to `ROUND_UP_REVERSE` for back-compat).
- **RUN ONCE** `migrateGuiQueueHeader_()` from the Apps Script editor
  to add the SIGNAL_TYPE column header to your existing GUI_QUEUE
  sheet and backfill existing rows with `ROUND_UP_REVERSE`. Idempotent.
- **EDIT** `runImportCore_` to also call the two new classifiers per
  filing and push additional `guiQueueRows` entries when they match.
  Full wiring example at the bottom of `phase5_signal_types.gs`.

The Python pipeline (`src/edgar/producer.py` + `src/gui/core/sheets.py`)
handles legacy 11-column sheets by defaulting SIGNAL_TYPE to
`ROUND_UP_REVERSE`, so you can stage this rollout: ship the Python
side first (already done), run for a week to verify nothing regresses,
THEN apply the Apps Script patches.

### GUI_QUEUE columns (v2.3)

| Col | Field | Meaning |
|---|---|---|
| A | CREATED_AT | timestamp written |
| B | TICKER | symbol to act on |
| C | ACTION | `buy` (pre-split / record date) |
| D | RATIO | reverse-split ratio OR `1-for-N` distribution ratio OR `$X.XX` for special-div |
| E | EFFECTIVE_DATE | effective date (reverse split) OR record date (spin-off / special-div) |
| F | PRESPLIT_DEADLINE | last buy time (prev market day, 4pm ET) — only meaningful for reverse splits |
| G | FRACTIONAL_POLICY | ROUND_UP / CASH_IN_LIEU / … (blank for spin-off / special-div) |
| H | CONFIDENCE | 0–1 |
| I | SOURCE | feed label / type |
| J | KEY | dedupe key (matches ANNOUNCEMENTS.KEY) |
| K | STATUS | `PENDING` — the GUI writes back `EXECUTED`/`FAILED`/`SKIPPED` |
| **L** | **SIGNAL_TYPE** | `ROUND_UP_REVERSE` / `SPIN_OFF` / `SPECIAL_DIV` |
