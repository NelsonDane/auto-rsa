# Corpus regression fixtures (local-only)

`corpus_test.py` is **data-driven** and skips cleanly when these files
are absent, so CI never depends on private data. Drop either file here
to activate its check. CSVs are gitignored.

## `hist_alerts_v1.csv` — real-money safety guard
Export the `hist_alerts_v1` tab as CSV (File → Download → CSV). Header
(exact, order-independent — matched by name):

```
TICKER,EFFECTIVE_DATE,SPLIT_RATIO_RAW,SPLIT_RATIO_NUM,PRICE_AT_ALERT,ANNOUNCED_FRACTIONAL_POLICY,ACTUAL_OUTCOME,RATIO_BUCKET,OUTCOME_CATEGORY,Notes
```

Ground truth is `ACTUAL_OUTCOME`. The test asserts that rows the
pipeline announced as ROUND_UP whose **actual** outcome was *not* a
round-up (cash-in-lieu / round-down / sold) stay at/under
`MAX_FALSE_ROUND_UP_RATE` — a false ROUND_UP is the only error that
loses real money.

## `corpus_evidence.csv` — classifier port parity
Export the SCORER / ANNOUNCEMENTS tab columns as CSV with a header
containing at least:

```
FRACTIONAL_EVIDENCE,FRACTIONAL_POLICY
```

The test re-runs the ported `parse_fractional_policy` on each evidence
snippet and asserts it reproduces the recorded policy at
`MIN_PARITY_RATE`, with **zero** dangerous flips (recorded non-play but
predicted ROUND_UP).

Adjust thresholds at the top of `corpus_test.py` once you see the
baseline numbers it prints.
