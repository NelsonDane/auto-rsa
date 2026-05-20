# AutoRSA — Setup Guide (Sheets access, corpus, deployment)

Everything you need to wire the Google Sheet, activate the corpus
regression guards, and run the EDGAR producer. Self-contained; no prior
GCP/dev experience assumed. The Mac Mini host steps are in
`deploy/macmini/RUNBOOK.md` (referenced at the end).

---

## Part A — Google service account (one-time)

The GUI reads `GUI_QUEUE` and the producer writes it. Both use a
**service account** (a robot Google identity), not your personal login.

### A1. Create a project
1. Go to <https://console.cloud.google.com/>.
2. Top bar → project dropdown → **New Project** → name it
   `autorsa` → **Create** → select it.

### A2. Enable the Sheets API
1. Left menu → **APIs & Services → Library**.
2. Search **Google Sheets API** → open it → **Enable**.
   (You do NOT need the Drive API — only the Sheets values API is used.)

### A3. Create the service account
1. **APIs & Services → Credentials → Create credentials → Service
   account**.
2. Name `autorsa-sheets` → **Create and continue** → skip the optional
   role/grant steps → **Done**.

### A4. Download its key file
1. Credentials → click the new service account → **Keys** tab.
2. **Add key → Create new key → JSON → Create**. A `.json` file
   downloads. **This is a secret — treat it like a password.**
3. Open it in a text editor; note the `client_email` value
   (looks like `autorsa-sheets@autorsa-xxxx.iam.gserviceaccount.com`).

### A5. Share ONLY the one spreadsheet with it
1. Open your **Claud RSA Project** spreadsheet in Google Sheets.
2. **Share** → paste the service account's `client_email`.
3. Role: **Editor** (the producer needs to append rows; the GUI only
   reads, Editor covers both). **Uncheck "Notify people."** → **Share**.
4. Do **not** share anything else with this account — its blast radius
   is now exactly this one spreadsheet.

### A6. Where the key goes
- **GUI (read):** Signals tab → "Google Sheet connection" → paste the
  full JSON into *Service-account JSON key*, paste the spreadsheet URL,
  Save.
- **Producer (write, on the Mac Mini):** save the JSON to
  `~/auto-rsa/creds/edgar-sa.json`, `chmod 600` it, and set
  `RSA_SHEETS_SA_JSON=@~/auto-rsa/creds/edgar-sa.json` (see runbook).

> Optional hardening: create **two** service accounts — a Viewer-shared
> one for the GUI and an Editor-shared one for the producer. Single
> account is fine to start.

---

## Part B — Apply the Apps Script GUI_QUEUE patch

The sheet only gets a `GUI_QUEUE` tab once the Apps Script writes it.
Apply patch **item 8 (`writeGuiQueue_` + `runImportCore_` edit)** from
`docs/appscript/README.md` to your bound Apps Script, then run the
import once. The Python producer also writes the same tab/schema, so
either source populates it; both are idempotent by KEY.

---

## Part C — Activate the corpus regression guards

These two CSVs turn on the precision tests (`edgar_tests/corpus_test.py`).
Until added, those tests **skip** (CI never depends on private data).
Both files go in **`edgar_tests/fixtures/`** and are gitignored.

### C1. `hist_alerts_v1.csv` (real-money safety guard)
1. Open the **Claud RSA Project** spreadsheet.
2. Click the **`hist_alerts_v1`** tab at the bottom.
3. **File → Download → Comma-separated values (.csv)**.
4. Rename the downloaded file to exactly `hist_alerts_v1.csv`.
5. Move it to `edgar_tests/fixtures/hist_alerts_v1.csv`.

Expected header (the test matches by **name**, so column order/extra
columns are fine):
`TICKER, EFFECTIVE_DATE, SPLIT_RATIO_RAW, SPLIT_RATIO_NUM,
PRICE_AT_ALERT, ANNOUNCED_FRACTIONAL_POLICY, ACTUAL_OUTCOME,
RATIO_BUCKET, OUTCOME_CATEGORY, Notes`.
The test flags any row announced **ROUND_UP** whose **ACTUAL_OUTCOME**
was not a round-up (the only error that loses money).

### C2. `corpus_evidence.csv` (classifier parity)
1. Same spreadsheet → the **SCORER** tab (or **ANNOUNCEMENTS** —
   whichever holds `FRACTIONAL_EVIDENCE` + `FRACTIONAL_POLICY`).
2. **File → Download → CSV**.
3. Rename to `corpus_evidence.csv`, move to
   `edgar_tests/fixtures/corpus_evidence.csv`.
   It just needs columns named `FRACTIONAL_EVIDENCE` and
   `FRACTIONAL_POLICY`; others are ignored.

### C3. Run the guards and read the baseline
```sh
cd ~/auto-rsa
.venv/bin/python -m pytest edgar_tests/corpus_test.py -q -s
```
`-s` prints the baseline numbers (parity %, false-ROUND_UP rate, and the
first ~20 mismatches). If parity/false-rate are close to the thresholds
at the top of `corpus_test.py`, tell me the printed numbers and I'll
tune the thresholds and investigate any dangerous mismatches.

---

## Part D — Always-on host

Deploy the producer on the Mac Mini with `deploy/macmini/RUNBOOK.md`
(from-clean-macOS: Terminal → Xcode CLT/git → Homebrew → `gh auth
login` → uv → clone → `uv sync` → SA key → launchd job).

---

## Env var reference

| Variable | Used by | Meaning |
|---|---|---|
| `RSA_SHEETS_SA_JSON` | producer `--write` | SA key: inline JSON or `@/path` |
| `RSA_SHEETS_ID` | producer `--write` | spreadsheet ID or URL |
| `RSA_SHEETS_WORKSHEET` | producer | tab name (default `GUI_QUEUE`) |
| `RSA_SEC_USER_AGENT` | producer | `"Name email"` for SEC requests |
| `RSA_ACCOUNT_FILTER` | engine | per-broker sub-account allow-list (set by the GUI) |
| `RSA_PLAY_KEY` / `RSA_PLAY_SPLIT_KEY` | engine | per-signal ledger keys (set automatically) |

GUI-managed values (vault) need no manual env. The producer env is set
by the launchd job in the runbook.
