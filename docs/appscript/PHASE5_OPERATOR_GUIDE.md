# Operator guide — Apps Script signal-type upgrade

**Estimated time: 15 minutes.** This is what you (the operator) do
in the Google Apps Script editor to teach the upstream scraper to
detect spin-offs and special dividends, plus thread a `SIGNAL_TYPE`
column through `GUI_QUEUE`. The Python side has already shipped and
is forward-compatible — your existing flow keeps working unchanged
until you finish this guide, and even after, all existing rows
default to `ROUND_UP_REVERSE` so nothing breaks.

## What this changes (and what it doesn't)

| Thing | Before | After |
|---|---|---|
| Reverse-split detection | Works | Works (unchanged) |
| Spin-off detection | None | **NEW** — Apps Script flags them, GUI surfaces them |
| Special-dividend detection | None | **NEW** — same |
| `GUI_QUEUE` columns | 11 | **12** (adds `SIGNAL_TYPE`) |
| Existing `GUI_QUEUE` rows | Stay as-is | Backfilled with `ROUND_UP_REVERSE` |
| Trading behavior | Buys round-ups only | Same (Phase 7 turns on the new types) |

**You can stop after this guide and trading behavior won't change.**
Detection without execution gives you a week of dry-run visibility
into which new signals appear before you decide whether to enable
trading them (that's the Phase 7 step).

## Prerequisites

- Your existing reverse-split Apps Script is working (you see new
  rows landing in `GUI_QUEUE` regularly).
- You can open the bound Apps Script editor (Sheet menu →
  Extensions → Apps Script).
- You've pulled the latest Python code and tests pass — confirm
  with the `release-safety-checker` agent or:
  ```
  uv run --no-sync python -m pytest edgar_tests/ gui_tests/ -q
  ```

## Step 1 — Add the new file to your Apps Script project

1. In the Apps Script editor, click the **+** next to "Files" → **Script**.
2. Name it `phase5_signal_types`.
3. Copy the **entire contents** of `docs/appscript/phase5_signal_types.gs`
   from this repo and paste into the new file.
4. Save (⌘S / Ctrl+S).

**Verify**: the file appears in the file list with no syntax errors
(no red underlines).

## Step 2 — Replace your existing `writeGuiQueue_` function

You already have a `writeGuiQueue_` function somewhere in your
script (likely in `reverse_split_patches.gs`). It writes 11 columns;
the new version writes 12.

1. In the Apps Script editor, search (⌘F / Ctrl+F) for
   `function writeGuiQueue_(`. There should be exactly one match in
   the OLD file — that's the one to replace.
2. **Delete the entire old `writeGuiQueue_` function** (from
   `function writeGuiQueue_(rows) {` through its closing `}`).
3. The new `writeGuiQueue_` is already in
   `phase5_signal_types.gs` (you pasted it in Step 1). Don't
   re-paste it.
4. Save.

**Verify**: only ONE `writeGuiQueue_` exists in your project. A
search for `function writeGuiQueue_` should return exactly one hit.

## Step 3 — Run the GUI_QUEUE migration ONCE

The existing `GUI_QUEUE` sheet has 11 columns. The migration adds
the `SIGNAL_TYPE` header and backfills existing rows with
`ROUND_UP_REVERSE` so the Python GUI keeps treating them correctly.

1. In the Apps Script editor, open `phase5_signal_types.gs`.
2. In the **function dropdown** at the top of the editor (next to
   the Run button), pick `migrateGuiQueueHeader_`.
3. Click **Run**.
4. First time only: Apps Script will ask for permission. Click
   **Review permissions** → choose your Google account → **Allow**.
5. After it completes, open the **Execution log** at the bottom.
   You should see one of:
   - `Migrated GUI_QUEUE: added SIGNAL_TYPE column at 12;
     backfilled N row(s) as ROUND_UP_REVERSE.` ← success
   - `SIGNAL_TYPE already present — no migration needed.` ← also
     success (you ran it twice; idempotent)
   - `GUI_QUEUE sheet does not exist — nothing to migrate.` ← the
     sheet will be created the next time signals are written;
     nothing to do here.

**Verify**: open the `GUI_QUEUE` sheet in your browser. Column **L**
header should read `SIGNAL_TYPE`. Every existing row should show
`ROUND_UP_REVERSE` in that column.

## Step 4 — Wire the new classifiers into `runImportCore_`

This is the only step that requires editing an existing function
(everything else was additive). You'll add two small blocks that
call `parseSpinOff_` and `parseSpecialDividend_` on each filing the
script already fetches.

1. Open the file in your project that contains `runImportCore_`
   (search the file list, it's likely your main script).
2. Find the per-filing loop where you already call
   `parseReverseSplit_(text)` and push to `guiQueueRows`. It looks
   roughly like:
   ```javascript
   const rs = parseReverseSplit_(text);
   if (rs.matched && rs.fractionalConf >= 0.60) {
     guiQueueRows.push({
       ticker, key, ratio: rs.ratio,
       effectiveDate: rs.effectiveDate,
       fractionalPolicy: rs.fractionalPolicy,
       fractionalConf: rs.fractionalConf,
       source: feedType,
     });
   }
   ```
3. **Immediately after that `if (rs.matched ...)` block**, paste:
   ```javascript
   // Phase 5: spin-off detection.
   const so = parseSpinOff_(text);
   if (so.matched && so.confidence >= 0.75) {
     guiQueueRows.push({
       ticker,
       key: key + ":SPIN_OFF",
       ratio: so.distRatio,
       effectiveDate: so.recordDate,
       fractionalPolicy: "",
       fractionalConf: so.confidence,
       source: feedType,
       signalType: "SPIN_OFF",
     });
   }

   // Phase 5: special-dividend detection.
   const sd = parseSpecialDividend_(text);
   if (sd.matched && sd.confidence >= 0.75) {
     const amtStr = sd.amountPerShare > 0 ? ("$" + sd.amountPerShare) : "";
     const primaryDate = sd.recordDate || sd.exDate || sd.paymentDate;
     guiQueueRows.push({
       ticker,
       key: key + ":SPECIAL_DIV",
       ratio: amtStr,
       effectiveDate: primaryDate,
       fractionalPolicy: "",
       fractionalConf: sd.confidence,
       source: feedType,
       signalType: "SPECIAL_DIV",
     });
   }
   ```
4. The `":SPIN_OFF"` / `":SPECIAL_DIV"` suffixes on `key` are
   important — they make sure a single filing that triggers both a
   reverse-split AND a spin-off produces two distinct GUI_QUEUE
   rows that don't dedupe against each other.
5. Save.

**Verify**: no syntax errors. The function dropdown should still
list `runImportCore_`.

## Step 5 — Test in safe mode first

1. At the top of your script, find `CONFIG.TEST_MODE`. If it's
   `false`, change to `true` temporarily.
2. Run `runImportCore_` from the function dropdown.
3. Open the Execution log. You should see normal output plus, if
   any spin-off or special-div filings appeared in the EDGAR
   window:
   - New rows in `GUI_QUEUE` with `SIGNAL_TYPE` = `SPIN_OFF` or
     `SPECIAL_DIV`.
   - No Discord pings for the new types (they haven't been wired
     into the Discord post helpers — by design, detection only
     for now).
4. Set `CONFIG.TEST_MODE` back to `false`.

**Verify**: `GUI_QUEUE` may or may not have new-type rows depending
on what's actually in EDGAR's window. If it doesn't, that's fine —
the script will pick them up the next time a filing matches.

## Step 6 — Open the Python GUI and confirm

1. Start the GUI: `./start-gui.command` (Mac) or `start-gui.cmd` (Win).
2. Unlock the vault, go to the **Signals** tab.
3. Click **Refresh signals**.
4. In the "All active signals" expander, every row should show a
   `SIGNAL_TYPE` value:
   - `ROUND_UP_REVERSE` for existing rows (backfilled by Step 3)
   - `SPIN_OFF` / `SPECIAL_DIV` for any new rows from Step 5

If the GUI raises a `SheetsError` complaining about a missing
column, double-check Step 3 actually ran and the header in column L
is exactly `SIGNAL_TYPE` (case-sensitive).

## Rollback (if needed)

If anything goes wrong:

1. **Disable the new classifiers** (Step 4): comment out the two
   `if (so.matched ...)` and `if (sd.matched ...)` blocks. The
   reverse-split flow keeps working.
2. **The migration is non-destructive** — your existing `GUI_QUEUE`
   data is intact in columns A–K. Removing the SIGNAL_TYPE column
   would also be safe (the Python GUI defaults to
   `ROUND_UP_REVERSE` when the column is absent).
3. If you want to go back to the old 11-column `writeGuiQueue_`,
   restore from your script's version history (Apps Script keeps
   one automatically — Editor → File menu → Version history).

## When to do Step 7 (Phase 7 — actually trade these)

**Don't enable trading on the new types until you've watched them
land for at least a week.** The classifier confidence floors are
conservative (≥ 0.75) but real filings have surprises. Once you've
seen a handful of `SPIN_OFF` and `SPECIAL_DIV` rows land and
verified they look right, you can flip the Phase 7 allow-list in
the GUI sidebar — that's a separate workflow with its own typed-
EXECUTE confirms.

---

Questions about this guide → ask in chat with the
`appscript-debugger` agent or just paste the Apps Script execution
log and I'll triage.
