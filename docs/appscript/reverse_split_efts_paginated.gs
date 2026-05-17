/**
 * v2.2.1 — Paginated SEC EDGAR full-text search (EFTS).
 * Drop-in replacement for fetchAndParseSecEFTS_ in the v2.2 script.
 * Same call signature and return contract (null on first-page hard
 * failure, [] on no hits, array otherwise). Pages through EFTS
 * (10 results/page) up to 100 filings/query, dedupes by filing id,
 * and stops at the real total — fixes the v2.2 "only first ~10 hits"
 * coverage gap.
 */
function fetchAndParseSecEFTS_(feedUrl, startDate, endDate) {
  const q = String(feedUrl || "").replace(/^EFTS::/, "").trim() || '"reverse stock split"';
  const PAGE = 10;          // EFTS fixed page size
  const MAX_PAGES = 10;     // safety cap (<=100 filings/query) for GAS quotas
  const out = [];
  const seenIds = new Set();
  let from = 0;
  let total = null;
  let hardFail = false;

  for (let page = 0; page < MAX_PAGES; page++) {
    const url =
      "https://efts.sec.gov/LATEST/search-index?q=" + encodeURIComponent(q) +
      "&forms=8-K&startdt=" + encodeURIComponent(startDate) +
      "&enddt=" + encodeURIComponent(endDate) +
      "&from=" + from;

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
      hardFail = (page === 0);
      break;
    }

    const code = resp.getResponseCode();
    Logger.log(`EFTS ${code} page=${page} from=${from} :: ${q}`);
    if (code !== 200) { hardFail = (page === 0); break; }

    let data;
    try {
      data = JSON.parse(resp.getContentText());
    } catch (e) {
      Logger.log("EFTS JSON parse error: " + e);
      hardFail = (page === 0);
      break;
    }

    const hits = (data && data.hits && data.hits.hits) || [];
    if (total === null) {
      const tv = data && data.hits && data.hits.total;
      total = (tv && typeof tv === "object") ? Number(tv.value || 0) : Number(tv || 0);
    }
    if (hits.length === 0) break;

    for (const h of hits) {
      const id = String(h._id || "");
      if (seenIds.has(id)) continue;
      seenIds.add(id);

      const src = h._source || {};
      const accession = id.split(":")[0] || "";
      const filename = id.split(":")[1] || "";
      const ciks = src.ciks || [];
      const cik = ciks.length ? String(ciks[0]).replace(/^0+/, "") : "";

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
        link, published, summary: "", ratio: "", ticker, cik,
      });
    }

    from += PAGE;
    if (total !== null && from >= total) break;   // walked everything
    if (hits.length < PAGE) break;                 // last (short) page
  }

  if (hardFail && out.length === 0) return null;   // first-page failure
  Logger.log(`EFTS parsed ${out.length} hits for ${q} (paged)`);
  return out;
}
