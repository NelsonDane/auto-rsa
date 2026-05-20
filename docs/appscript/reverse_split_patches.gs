/**
 * Reverse-Split Automation — patch set v2.1 -> v2.2
 * Apply each block in order. "REPLACE" = swap the whole named function.
 * "ADD" = paste as a new function. "EDIT" = make the small change shown.
 * Test with CONFIG.TEST_MODE = true first.
 */

/* ════════════════════════════════════════════════════════════════════
 * 1) EDIT runImportCore_
 *    Inside the inner `for (const item of items)` loop you currently have:
 *        newRows.push(rowObj);
 *        existingKeys.add(key);
 *        runManualOverrides();          // <-- DELETE THIS LINE
 *    Remove that runManualOverrides() call. Then, lower down, just
 *    before `if (newRows.length === 0) return;` ADD one call:
 *        runManualOverrides();          // once per run, not per item
 *    (Better still: give runManualOverrides its own time-based trigger.)
 * ════════════════════════════════════════════════════════════════════ */


/* ════════════════════════════════════════════════════════════════════
 * 2) ADD urlCacheKey_  + EDIT the two cache-key lines
 *    In getCachedSecFilingText_ replace:
 *        const key = "SEC2_" + Utilities.base64EncodeWebSafe(url).slice(0, 90);
 *    with:
 *        const key = urlCacheKey_("SEC2_", url);
 *    In getCachedArticleText_ replace:
 *        const key = "ART2_" + Utilities.base64EncodeWebSafe(url).slice(0, 90);
 *    with:
 *        const key = urlCacheKey_("ART2_", url);
 * ════════════════════════════════════════════════════════════════════ */
function urlCacheKey_(prefix, url) {
  // Full-URL SHA-256 -> no prefix collisions on long, similar SEC URLs
  // (the old slice(0,90) returned another filing's cached body).
  const digest = Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256,
    String(url || "")
  );
  const hex = digest
    .map(b => ((b & 0xff) + 0x100).toString(16).slice(1))
    .join("");
  return prefix + hex;
}


/* ════════════════════════════════════════════════════════════════════
 * 3) ADD SEC EFTS full-text feed (authoritative 8-K detection).
 *    Then ADD these to CONFIG.FEEDS (sec_daily_index can stay or go):
 *      { url: "EFTS::\"reverse stock split\"", type: "sec_efts",
 *        label: "SEC EFTS: reverse stock split" },
 *      { url: "EFTS::\"reverse split\"",        type: "sec_efts",
 *        label: "SEC EFTS: reverse split" },
 *    And in runImportCore_'s switch(feedType) add a case:
 *      case "sec_efts":
 *        items = fetchAndParseSecEFTS_(feedUrl, secStartDate, secEndDate);
 *        break;
 * ════════════════════════════════════════════════════════════════════ */
function fetchAndParseSecEFTS_(feedUrl, startDate, endDate) {
  // feedUrl looks like  EFTS::"reverse stock split"
  const q = String(feedUrl || "").replace(/^EFTS::/, "").trim() || '"reverse stock split"';
  const params =
    "q=" + encodeURIComponent(q) +
    "&forms=8-K" +
    "&startdt=" + encodeURIComponent(startDate) +
    "&enddt=" + encodeURIComponent(endDate);
  const url = "https://efts.sec.gov/LATEST/search-index?" + params;

  Utilities.sleep(CONFIG.SEC_FETCH_SLEEP_MS);
  let resp;
  try {
    resp = UrlFetchApp.fetch(url, {
      muteHttpExceptions: true,
      followRedirects: true,
      headers: {
        "User-Agent": `${CONFIG.CONTACT_NAME} ${CONFIG.CONTACT_EMAIL}`,
        "Accept": "application/json",
      },
    });
  } catch (e) {
    Logger.log("EFTS fetch error: " + e);
    return null;
  }

  const code = resp.getResponseCode();
  Logger.log(`EFTS ${code} :: ${url}`);
  if (code !== 200) return null;

  let data;
  try {
    data = JSON.parse(resp.getContentText());
  } catch (e) {
    Logger.log("EFTS JSON parse error: " + e);
    return null;
  }

  const hits = (data && data.hits && data.hits.hits) || [];
  const out = [];

  for (const h of hits) {
    const src = h._source || {};
    const id = String(h._id || "");                  // ACCESSION:FILENAME
    const accession = id.split(":")[0] || "";
    const filename = id.split(":")[1] || "";
    const ciks = src.ciks || [];
    const cik = ciks.length ? String(ciks[0]).replace(/^0+/, "") : "";

    // display_names like:  "Acme Corp (ACME) (CIK 0001234567)"
    const dn = (src.display_names && src.display_names[0]) || "";
    let ticker = null;
    const tm = dn.match(/\(([A-Z]{1,6})\)\s*\(CIK/i);
    if (tm) ticker = tm[1].toUpperCase();

    let link = "";
    if (cik && accession) {
      const accNoDash = accession.replace(/-/g, "");
      link =
        `https://www.sec.gov/Archives/edgar/data/${cik}/${accNoDash}/` +
        (filename || (accession + "-index.htm"));
    }

    let published = null;
    if (src.file_date) {
      const d = new Date(src.file_date + "T00:00:00-05:00");
      if (!isNaN(d.getTime())) published = d;
    }

    if (!link) continue;

    out.push({
      title: `${dn || "8-K"} — reverse split (8-K)`,
      link,
      published,
      summary: "",
      ratio: "",
      ticker,
      cik,
    });
  }

  Logger.log(`EFTS parsed ${out.length} hits for ${q}`);
  return out;
}


/* ════════════════════════════════════════════════════════════════════
 * 4) REPLACE parseReverseSplit_
 *    - ratio: ONLY accept reverse (1-for-N, N>=2). A forward split
 *      ("2-for-1") no longer becomes a false RSA BUY.
 *    - effective date: adds ISO, MM/DD/YYYY, ordinals, "close of
 *      business on", "on or about".
 * ════════════════════════════════════════════════════════════════════ */
function parseReverseSplit_(text) {
  const out = { ticker: null, ratio: null, effectiveDate: null, reason: null };
  const s = String(text || "");

  let m = s.match(/\((?:NASDAQ|NYSE|AMEX|NYSEAMERICAN|NYSE\s*AMERICAN|OTC|OTCQB|OTCQX)\s*:\s*([A-Z]{1,6})\)/i);
  if (m) out.ticker = m[1].toUpperCase();
  if (!out.ticker) {
    m = s.match(/\|\s*([A-Z]{1,6})\s+Stock News\b/i);
    if (m) out.ticker = m[1].toUpperCase();
  }
  if (!out.ticker) {
    m = s.match(/Trading\s+Symbol\s*[:\-]\s*([A-Z]{1,6})\b/i);
    if (m) out.ticker = m[1].toUpperCase();
  }

  // REVERSE ratio only: "1-for-N", "1 for N", "1:N", "1 to N", N>=2.
  const rev =
    s.match(/\b1\s*[-\s]?for[-\s]?(\d+)\b/i) ||
    s.match(/\b1\s*:\s*(\d{1,5})\b/) ||
    s.match(/\b1\s*[-\s]?to[-\s]?(\d+)\b/i);
  if (rev) {
    const n = Number(rev[1]);
    if (n >= 2 && n <= 100000) out.ratio = `1-for-${n}`;
  }

  // Effective date — several phrasings.
  const MONTH = "(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)";
  const dateRes = [
    new RegExp(`effective(?:\\s+(?:on|as of))?\\s+(?:on or about\\s+)?(${MONTH}\\.?\\s+\\d{1,2}(?:st|nd|rd|th)?,?\\s+\\d{4})`, "i"),
    new RegExp(`(?:become|becomes|will be|is expected to be|is scheduled to be)\\s+effective\\s+(?:on\\s+)?(?:on or about\\s+)?(${MONTH}\\.?\\s+\\d{1,2}(?:st|nd|rd|th)?,?\\s+\\d{4})`, "i"),
    new RegExp(`effective\\s+date\\s+(?:of|is|will be)\\s+(${MONTH}\\.?\\s+\\d{1,2}(?:st|nd|rd|th)?,?\\s+\\d{4})`, "i"),
    new RegExp(`(?:close of business on|as of the close of business on)\\s+(${MONTH}\\.?\\s+\\d{1,2}(?:st|nd|rd|th)?,?\\s+\\d{4})`, "i"),
    /effective[^.]{0,40}\b(\d{4}-\d{2}-\d{2})\b/i,
    /effective[^.]{0,40}\b(\d{1,2}\/\d{1,2}\/\d{4})\b/i,
  ];
  for (const re of dateRes) {
    m = s.match(re);
    if (m) { out.effectiveDate = m[1].replace(/(st|nd|rd|th)/i, ""); break; }
  }

  if (/nasdaq.*compliance|minimum bid|bid price|listing compliance|price deficiency/i.test(s)) {
    out.reason = "Compliance";
  }
  return out;
}


/* ════════════════════════════════════════════════════════════════════
 * 5) REPLACE parseTickerGeneric_
 *    Removes the unsafe bare "(ABCD)" fallback and adds a stop-list so
 *    "(USA)"/"(CEO)"/"(SEC)" can never become a !rsa buy target.
 * ════════════════════════════════════════════════════════════════════ */
const TICKER_STOPLIST_ = new Set([
  "USA","CEO","CFO","COO","CTO","SEC","FAQ","NYSE","ETF","IPO","USD",
  "NEWS","AI","LLC","INC","LTD","PLC","NA","US","UK","EU","FDA","GAAP",
  "EPS","ROI","API","URL","PDF","ESG","CUSIP","OTC","ADR","ADS","SPAC",
]);
function parseTickerGeneric_(text) {
  const s = String(text || "");
  const ok = t => {
    const u = String(t || "").toUpperCase();
    return u && !TICKER_STOPLIST_.has(u) ? u : null;
  };

  let m = s.match(/\|\s*([A-Z]{1,6})\s+Stock News\b/);
  if (m && ok(m[1])) return ok(m[1]);

  m = s.match(/\((?:NASDAQ|NYSE|AMEX|NYSEAMERICAN|NYSE\s*AMERICAN|OTC|OTCQB|OTCQX|Cboe)\s*:\s*([A-Z]{1,6})\)/i);
  if (m && ok(m[1])) return ok(m[1]);

  m = s.match(/\b(?:NASDAQ|NYSE|AMEX|NYSEAMERICAN|NYSE\s*AMERICAN)\s*:\s*([A-Z]{1,6})\b/i);
  if (m && ok(m[1])) return ok(m[1]);

  m = s.match(/\$([A-Z]{1,6})\b/);
  if (m && ok(m[1])) return ok(m[1]);

  m = s.match(/\b(?:trading\s+)?(?:symbol|ticker)\s*[:\-]\s*([A-Z]{1,6})\b/i);
  if (m && ok(m[1])) return ok(m[1]);

  // NOTE: deliberately NO bare "(ABCD)" fallback — too unsafe for an
  // auto-buy pipeline. Prefer a missed ticker over a wrong one.
  return null;
}


/* ════════════════════════════════════════════════════════════════════
 * 6) ADD postFeedHealthAlert_  + EDIT runImportCore_
 *    After the SUMMARY Logger.log(...) in runImportCore_, ADD:
 *      postFeedHealthAlert_({
 *        feedsOk, feedsFailed, itemsSeen, newRows: newRows.length,
 *        backtest: !!opts.backtest
 *      });
 *
 *    v2.2.2 — QUIETER: a couple of feeds failing while others work and
 *    items are still seen is NORMAL (StockTitan/SEC rate-limits), so it
 *    no longer Discord-spams every run. It Logger.log()s every run for
 *    debugging, but only POSTS to Discord on a genuine outage
 *    (feedsOk===0 OR itemsSeen===0), and then at most once per 12h
 *    (ScriptProperties throttle). To silence Discord entirely, set
 *    CONFIG.HEALTH_ALERTS = false.
 * ════════════════════════════════════════════════════════════════════ */
function postFeedHealthAlert_(stats) {
  // Always log — cheap, inspectable in Apps Script execution logs.
  const line = [
    "RSA Scraper health",
    `feedsOk=${stats.feedsOk} feedsFailed=${stats.feedsFailed}`,
    `itemsSeen=${stats.itemsSeen} newRows=${stats.newRows}`,
    `backtest=${stats.backtest} at ${new Date().toLocaleString()}`,
  ].join(" | ");
  Logger.log(line);

  if (stats.backtest) return;                       // backtests never alert
  if (CONFIG.HEALTH_ALERTS === false) return;       // hard off switch

  // Only a real outage is worth pinging: every feed failed, or nothing
  // at all was fetched. Some feeds failing while others succeed and
  // items were seen is expected and must NOT alert.
  const outage = (stats.feedsOk === 0) || (stats.itemsSeen === 0);
  if (!outage) return;

  // Throttle: at most one outage ping per 12h, even across many runs.
  const props = PropertiesService.getScriptProperties();
  const now = Date.now();
  const last = Number(props.getProperty("HEALTH_ALERT_LAST") || 0);
  if (now - last < 12 * 60 * 60 * 1000) return;

  const servers = getActiveDiscordServers_();
  const targets = servers.filter(s => s.signalUrl);
  if (CONFIG.TEST_MODE || targets.length === 0) return;

  props.setProperty("HEALTH_ALERT_LAST", String(now));
  const msg = "🔴 RSA Scraper OUTAGE\n" + line;
  targets.forEach(s => {
    try {
      UrlFetchApp.fetch(s.signalUrl, {
        method: "post",
        contentType: "application/json",
        payload: JSON.stringify({ content: msg.slice(0, 1900) }),
        muteHttpExceptions: true,
      });
    } catch (e) {
      Logger.log("health alert post error: " + e);
    }
  });
}


/* ════════════════════════════════════════════════════════════════════
 * 7) ADD isImminent_  + EDIT formatDiscordRSASignal_
 *    In formatDiscordRSASignal_, after `const preSplit = ...`, ADD:
 *      const urgent = isImminent_(effDateObj) ? "🔴 URGENT — buy deadline is today/tomorrow\n" : "";
 *    and prepend `urgent` to the returned joined string (e.g. return urgent + [ ... ].join("\n");)
 * ════════════════════════════════════════════════════════════════════ */
function isImminent_(effDateObj) {
  if (!effDateObj || !(effDateObj instanceof Date) || isNaN(effDateObj.getTime())) return false;
  const deadline = previousMarketDay_(effDateObj);          // last buy day
  const today = normalizeNoon_(new Date());
  const diffDays = Math.round((deadline.getTime() - today.getTime()) / 86400000);
  return diffDays <= 1;   // deadline is today or tomorrow (or already past)
}


/* ════════════════════════════════════════════════════════════════════
 * 8) ADD writeGuiQueue_  + EDIT runImportCore_
 *    In the `newRows.forEach(r => { ... })` Discord block, after
 *    `postDiscordRsaBuyCommand_(t);` ADD:
 *        guiQueueRows.push(r);
 *    Declare `const guiQueueRows = [];` just before that forEach, and
 *    after the forEach ADD:
 *        writeGuiQueue_(guiQueueRows);
 *    This is the local-GUI integration contract (no Discord needed).
 * ════════════════════════════════════════════════════════════════════ */
function writeGuiQueue_(rows) {
  if (!rows || rows.length === 0) return;
  const ss = SpreadsheetApp.getActive();
  let sh = ss.getSheetByName("GUI_QUEUE");
  if (!sh) sh = ss.insertSheet("GUI_QUEUE");

  const header = [
    "CREATED_AT","TICKER","ACTION","RATIO","EFFECTIVE_DATE",
    "PRESPLIT_DEADLINE","FRACTIONAL_POLICY","CONFIDENCE","SOURCE",
    "KEY","STATUS",
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
    ]);
    existing.add(String(r.key));
  });

  if (data.length) {
    sh.getRange(sh.getLastRow() + 1, 1, data.length, header.length).setValues(data);
  }
}
