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
   turns silent feed/Discord failures into a visible heartbeat
   (a prime cause of "missing some alerts").
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
