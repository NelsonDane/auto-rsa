/* ════════════════════════════════════════════════════════════════════
 * Phase 5 (signal types) patches for the bound Apps Script.
 *
 * Adds detection for SPIN_OFF and SPECIAL_DIV signal classes alongside
 * the existing ROUND_UP_REVERSE flow, and threads a SIGNAL_TYPE column
 * through GUI_QUEUE so the Python GUI's plan_signals can gate per
 * type. Backward-compatible: existing 11-column sheets are migrated
 * in place (column 12 added + existing rows backfilled with
 * ROUND_UP_REVERSE).
 *
 * APPLY ORDER:
 *   1. Open the bound Apps Script project for the existing sheet.
 *   2. Paste the four new functions below as a new file (or append to
 *      reverse_split_patches.gs).
 *   3. REPLACE writeGuiQueue_ with the version below.
 *   4. EDIT runImportCore_ — in the loop where you classify each item,
 *      AFTER parseReverseSplit_ runs and the row is queued, ALSO call
 *      parseSpinOff_ + parseSpecialDividend_ on the same text. If
 *      either matches with confidence ≥ 0.75, push a SECOND
 *      guiQueueRows entry with signalType set accordingly. See the
 *      example wiring at the bottom of this file.
 *   5. Run migrateGuiQueueHeader_() ONCE manually from the Apps Script
 *      editor's "Run" menu. This adds the SIGNAL_TYPE column to the
 *      existing GUI_QUEUE sheet and backfills existing rows. Idempotent.
 *
 * The Python EDGAR producer (src/edgar/producer.py) already handles
 * legacy 11-column sheets by defaulting SIGNAL_TYPE to
 * ROUND_UP_REVERSE — so even if you delay this Apps Script upgrade,
 * nothing breaks. You just don't get spin-off/special-div alerts
 * from the Apps Script path until you ship this.
 * ════════════════════════════════════════════════════════════════════ */


/* ---------------------------------------------------------------------
 * parseSpinOff_(text) -> { matched, confidence, recordDate, distRatio,
 *                          evidence }
 *
 * Apps Script port of src/edgar/classify.py:parse_spin_off. Requires
 * a STRONG trigger phrase AND a supporting term. Returns matched=false
 * (not just low conf) when the strong phrase has no supporting context
 * — false positives cost more than misses here.
 * ------------------------------------------------------------------- */
function parseSpinOff_(text) {
  const empty = {
    matched: false, confidence: 0.0, recordDate: "",
    distRatio: "", evidence: "",
  };
  const s = String(text || "");
  if (!s.trim()) return empty;

  const STRONG = new RegExp(
    "(spin-?off|spin\\s+off"
    + "|separation\\s+(of|into)\\s+(two|a)\\s+(separate|publicly[-\\s]traded|independent)"
    + "|distribution\\s+of\\s+(one\\s+share|shares?)\\s+of\\s+[A-Z][\\w\\s.]+\\s+common\\s+stock"
    + "|distribute\\s+(all|substantially\\s+all)\\s+of\\s+the\\s+(outstanding\\s+)?shares?"
    + ")",
    "i",
  );
  const SUPPORTING = new RegExp(
    "(record\\s+date|distribution\\s+date|ex-?distribution"
    + "|share\\s+distribution\\s+ratio|holders?\\s+of\\s+record"
    + "|board\\s+of\\s+directors?\\s+(authoriz|approv))",
    "i",
  );
  const DIST_RATIO = new RegExp(
    "(?:one|1)\\s+share\\s+of\\s+(?:[A-Z][\\w\\s.]+\\s+)?common\\s+stock"
    + "[^.]{0,40}?for\\s+every\\s+(\\d+)\\s+shares?",
    "i",
  );
  const RECORD_DATE = new RegExp(
    "record\\s+date[^.]{0,80}?"
    + "(\\w+\\s+\\d{1,2},?\\s+\\d{4}|\\d{4}-\\d{2}-\\d{2}|\\d{1,2}/\\d{1,2}/\\d{2,4})",
    "i",
  );

  const strong = STRONG.exec(s);
  if (!strong) return empty;
  if (!SUPPORTING.test(s)) {
    return {
      matched: false, confidence: 0.20, recordDate: "",
      distRatio: "", evidence: snippet_(s, strong.index, strong[0].length),
    };
  }

  let conf = 0.65;
  let distRatio = "";
  const dm = DIST_RATIO.exec(s);
  if (dm) { distRatio = "1-for-" + dm[1]; conf += 0.15; }

  let recordDate = "";
  const rm = RECORD_DATE.exec(s);
  if (rm) { recordDate = rm[1]; conf += 0.10; }

  return {
    matched: true, confidence: Math.min(conf, 0.95),
    recordDate: recordDate, distRatio: distRatio,
    evidence: snippet_(s, strong.index, strong[0].length),
  };
}

/* ---------------------------------------------------------------------
 * parseSpecialDividend_(text) -> { matched, confidence,
 *                                   amountPerShare, exDate, recordDate,
 *                                   paymentDate, evidence }
 * ------------------------------------------------------------------- */
function parseSpecialDividend_(text) {
  const empty = {
    matched: false, confidence: 0.0, amountPerShare: 0.0,
    exDate: "", recordDate: "", paymentDate: "", evidence: "",
  };
  const s = String(text || "");
  if (!s.trim()) return empty;

  const STRONG = new RegExp(
    "(special\\s+(cash\\s+)?dividend"
    + "|extraordinary\\s+(cash\\s+)?dividend"
    + "|one-?time\\s+(cash\\s+)?dividend"
    + "|special\\s+(cash\\s+)?distribution)",
    "i",
  );
  const REGULAR = new RegExp(
    "(quarterly\\s+(cash\\s+)?dividend|regular\\s+(cash\\s+)?dividend"
    + "|increase[ds]?\\s+(its\\s+)?(quarterly\\s+)?dividend)",
    "i",
  );
  const AMOUNT = new RegExp(
    "(?:special\\s+(?:cash\\s+)?dividend|extraordinary\\s+(?:cash\\s+)?dividend"
    + "|one-?time\\s+(?:cash\\s+)?dividend)[^$]{0,80}?"
    + "\\$\\s?(\\d+(?:\\.\\d{1,4})?)\\s*per\\s+share",
    "i",
  );
  const DATE = new RegExp(
    "(ex-?dividend\\s+date|record\\s+date|of\\s+record(?:\\s+as\\s+of)?"
    + "|payable\\s+(?:on)?|payment\\s+date)[^.]{0,80}?"
    + "(\\w+\\s+\\d{1,2},?\\s+\\d{4}|\\d{4}-\\d{2}-\\d{2}|\\d{1,2}/\\d{1,2}/\\d{2,4})",
    "ig",
  );

  const strong = STRONG.exec(s);
  if (!strong) return empty;

  if (REGULAR.test(s)) {
    if (!AMOUNT.test(s)) {
      return {
        matched: false, confidence: 0.25, amountPerShare: 0.0,
        exDate: "", recordDate: "", paymentDate: "",
        evidence: snippet_(s, strong.index, strong[0].length),
      };
    }
  }

  let conf = 0.70;
  let amount = 0.0;
  const am = AMOUNT.exec(s);
  if (am) { amount = parseFloat(am[1]) || 0.0; if (amount) conf += 0.15; }

  let exDate = "", recordDate = "", paymentDate = "";
  let m;
  while ((m = DATE.exec(s)) !== null) {
    const label = m[1].toLowerCase();
    if (label.indexOf("ex") !== -1 && !exDate) exDate = m[2];
    else if (label.indexOf("record") !== -1 && !recordDate) recordDate = m[2];
    else if ((label.indexOf("payable") !== -1 || label.indexOf("payment") !== -1)
             && !paymentDate) paymentDate = m[2];
  }
  if (exDate || recordDate || paymentDate) conf += 0.10;

  return {
    matched: true, confidence: Math.min(conf, 0.95),
    amountPerShare: amount, exDate: exDate, recordDate: recordDate,
    paymentDate: paymentDate,
    evidence: snippet_(s, strong.index, strong[0].length),
  };
}

function snippet_(text, idx, len) {
  const start = Math.max(0, idx - 80);
  const end = Math.min(text.length, idx + len + 80);
  return text.substring(start, end).replace(/\s+/g, " ").trim();
}


/* ---------------------------------------------------------------------
 * writeGuiQueue_ (REPLACES the v2 version)
 *
 * The 12th column carries SIGNAL_TYPE. Default for legacy callers
 * that don't pass r.signalType is ROUND_UP_REVERSE so existing
 * pipelines keep working unchanged.
 * ------------------------------------------------------------------- */
function writeGuiQueue_(rows) {
  if (!rows || rows.length === 0) return;
  const ss = SpreadsheetApp.getActive();
  let sh = ss.getSheetByName("GUI_QUEUE");
  if (!sh) sh = ss.insertSheet("GUI_QUEUE");

  const header = [
    "CREATED_AT","TICKER","ACTION","RATIO","EFFECTIVE_DATE",
    "PRESPLIT_DEADLINE","FRACTIONAL_POLICY","CONFIDENCE","SOURCE",
    "KEY","STATUS","SIGNAL_TYPE",
  ];
  if (sh.getLastRow() === 0) sh.appendRow(header);

  // Don't re-queue a KEY already present.
  const existing = new Set();
  if (sh.getLastRow() > 1) {
    sh.getRange(2, 10, sh.getLastRow() - 1, 1).getValues()
      .forEach(r => { if (r[0]) existing.add(String(r[0])); });
  }

  const now = new Date();
  const data = [];
  rows.forEach(r => {
    const t = String(r.ticker || "").trim().toUpperCase();
    if (!t || !r.key || existing.has(String(r.key))) return;
    const effObj = parseEffectiveDateToDate_(r.effectiveDate);
    data.push([
      now,
      t,
      "buy",
      r.ratio || "",
      r.effectiveDate || "",
      effObj ? computePreSplitText_(effObj) : "",
      r.fractionalPolicy || "",
      Number(r.fractionalConf || 0),
      r.source || r.feedType || "",
      String(r.key),
      "PENDING",
      String(r.signalType || "ROUND_UP_REVERSE").toUpperCase(),
    ]);
    existing.add(String(r.key));
  });

  if (data.length) {
    sh.getRange(sh.getLastRow() + 1, 1, data.length, header.length).setValues(data);
  }
}


/* ---------------------------------------------------------------------
 * migrateGuiQueueHeader_  (run ONCE manually after first deploy)
 *
 * Adds the SIGNAL_TYPE column to an existing 11-column GUI_QUEUE.
 * Backfills existing rows with ROUND_UP_REVERSE so plan_signals
 * keeps treating them as today. Idempotent — safe to re-run.
 * ------------------------------------------------------------------- */
function migrateGuiQueueHeader_() {
  const ss = SpreadsheetApp.getActive();
  const sh = ss.getSheetByName("GUI_QUEUE");
  if (!sh) {
    Logger.log("GUI_QUEUE sheet does not exist — nothing to migrate.");
    return;
  }
  if (sh.getLastRow() === 0) {
    Logger.log("GUI_QUEUE is empty — first run of upgraded writeGuiQueue_ will write the new header.");
    return;
  }
  const headerRange = sh.getRange(1, 1, 1, sh.getLastColumn());
  const header = headerRange.getValues()[0];

  if (header.indexOf("SIGNAL_TYPE") !== -1) {
    Logger.log("SIGNAL_TYPE already present — no migration needed.");
    return;
  }

  const newColIdx = header.length + 1;
  sh.getRange(1, newColIdx).setValue("SIGNAL_TYPE");

  const lastRow = sh.getLastRow();
  if (lastRow > 1) {
    const backfill = [];
    for (let i = 0; i < lastRow - 1; i++) backfill.push(["ROUND_UP_REVERSE"]);
    sh.getRange(2, newColIdx, backfill.length, 1).setValues(backfill);
  }
  Logger.log(
    "Migrated GUI_QUEUE: added SIGNAL_TYPE column at " + newColIdx
    + "; backfilled " + (lastRow - 1) + " row(s) as ROUND_UP_REVERSE.",
  );
}


/* ---------------------------------------------------------------------
 * Wiring example for runImportCore_
 *
 * In the per-filing loop where you already call parseReverseSplit_(text)
 * and push a row when it matches, add:
 *
 *   // Existing reverse-split path (unchanged): pushes a row with
 *   // signalType="ROUND_UP_REVERSE" (default).
 *   const rs = parseReverseSplit_(text);
 *   if (rs.matched && rs.fractionalConf >= 0.60) {
 *     guiQueueRows.push({ ticker, key, ratio: rs.ratio,
 *       effectiveDate: rs.effectiveDate,
 *       fractionalPolicy: rs.fractionalPolicy,
 *       fractionalConf: rs.fractionalConf, source: feedType });
 *   }
 *
 *   // NEW: spin-off detection.
 *   const so = parseSpinOff_(text);
 *   if (so.matched && so.confidence >= 0.75) {
 *     guiQueueRows.push({ ticker, key: key + ":SPIN_OFF",
 *       ratio: so.distRatio, effectiveDate: so.recordDate,
 *       fractionalPolicy: "", fractionalConf: so.confidence,
 *       source: feedType, signalType: "SPIN_OFF" });
 *   }
 *
 *   // NEW: special-dividend detection.
 *   const sd = parseSpecialDividend_(text);
 *   if (sd.matched && sd.confidence >= 0.75) {
 *     const amtStr = sd.amountPerShare > 0 ? ("$" + sd.amountPerShare) : "";
 *     const primaryDate = sd.recordDate || sd.exDate || sd.paymentDate;
 *     guiQueueRows.push({ ticker, key: key + ":SPECIAL_DIV",
 *       ratio: amtStr, effectiveDate: primaryDate,
 *       fractionalPolicy: "", fractionalConf: sd.confidence,
 *       source: feedType, signalType: "SPECIAL_DIV" });
 *   }
 *
 * The `key + ":SPIN_OFF"` / `":SPECIAL_DIV"` suffixes are CRITICAL
 * so a filing that triggers both reverse-split AND spin-off (rare but
 * possible) produces two distinct GUI_QUEUE rows that don't dedupe
 * against each other in writeGuiQueue_'s KEY check.
 * ------------------------------------------------------------------- */
