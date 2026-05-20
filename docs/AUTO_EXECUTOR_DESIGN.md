# Design: optional fully-automatic batch executor (M5 — FOR REVIEW)

Status: **proposal, not built.** This scopes a headless component that
consumes `GUI_QUEUE` and places real 1-share buys with **no human in
the loop**. It is deliberately separate from the manual M4 trigger
because removing the human gate is a real-money autonomy decision.

## 1. Goal

On a schedule (Mac Mini, after the producer), for every `PENDING`
confirmed-`ROUND_UP` signal: buy exactly 1 share in each allowed
sub-account, record it, and never double-buy — unattended.

## 2. Where it runs

New entrypoint `python -m src.edgar.execute` (sibling of the producer),
launched by a second `launchd` job a few minutes after the producer.
Reuses: `sheets.fetch_signals` (read), `signal_plan.plan_signals`, the
ledger, and the existing single-instance `run.lock`.

## 3. Flow

1. Acquire `run.lock` (abort if a GUI/engine run is active).
2. **Market-hours gate** — abort unless US equities are open
   (`market_calendar`); avoids the unresolved Fidelity after-hours
   limit problem entirely.
3. `fetch_signals` → `plan_signals(is_done=ledger.economic_done)`.
4. Apply **run caps** (see §4). Take the first N actionable plays.
5. For each play, sequentially: invoke the **headless engine** with
   `action=buy amount=1 ticker=… brokers=<eligible> dry=false` and env
   `RSA_PLAY_KEY`, `RSA_PLAY_SPLIT_KEY`, `RSA_ACCOUNT_FILTER`. The M1
   broker guard enforces the per-account filter and ledger idempotency
   (incl. cross-feed `split_key`); quantity is already hard-capped at 1.
6. Emit a per-play result line to the audit log + a completion webhook.
7. Optional: write `STATUS=EXECUTED/FAILED` back to `GUI_QUEUE`
   (needs write scope; the dashboard already derives status from the
   ledger, so this is cosmetic and optional).

## 4. Safety model (all mandatory before any LIVE enablement)

- **Hard qty = 1** (already enforced in `start_signal_run`).
- **Account filter required**: refuse to run if `RSA_ACCOUNT_FILTER`
  is empty for an eligible broker — never trade "all accounts"
  unattended.
- **Broker allowlist**: only brokers explicitly listed in
  `RSA_AUTO_BROKERS` are eligible (start: Fidelity only, once M1 is
  market-hours validated).
- **Run caps**: `RSA_AUTO_MAX_PLAYS` per run and
  `RSA_AUTO_MAX_ACCOUNTS` per play; exceeding → execute up to the cap,
  alert, stop.
- **Kill switch**: presence of `creds/AUTOEXEC_DISABLED` (or
  `RSA_AUTO_DISABLED=1`) makes the run a no-op + alert. Default OFF =
  disabled (opt-in).
- **Ledger is authoritative**: `INTENDED` (stuck/crash mid-order) is
  never auto-retried — it halts that play and alerts for human
  resolution (consistent with the M1 ledger contract). `FAILED` is
  retryable up to `RSA_AUTO_MAX_RETRIES`.
- **Notify always**: every run posts a summary (plays attempted,
  EXECUTED/FAILED/SKIPPED, caps hit) to the completion webhook so the
  user sees unattended activity.
- **Dry-run default**: `--write`/`--live` must be explicit; bare run is
  a no-op preview that logs what it *would* do.

## 5. The key blocker: unattended 2FA

Browser brokers (Fidelity/Chase) may prompt for an OTP at login. The
manual path bridges that prompt to the GUI; **headless has no human to
answer it.** Options, in order of preference:

1. **Persisted browser session / cookies** — reuse a logged-in profile
   so login skips OTP within its validity window. Most robust; needs a
   periodic manual re-auth and secure profile storage.
2. **TOTP automation** — if the broker offers an authenticator-app
   secret, generate the code with `pyotp` (already a dep). Works only
   where the broker supports TOTP (not SMS/push).
3. **Restrict the allowlist** to brokers/accounts that don't challenge
   on a trusted device/IP (the Mac Mini's static internal IP helps).

This must be resolved per broker before that broker joins
`RSA_AUTO_BROKERS`. Recommendation: start with whichever single broker
can sustain an unattended session, behind tight caps.

## 6. Failure handling

| Situation | Behavior |
|---|---|
| Broker login fails | skip its plays, alert, continue others |
| Order rejected (FAILED) | ledger FAILED (retryable next run, capped) |
| Mid-order/unknown (INTENDED) | halt that play, alert, **no auto-retry** |
| Market closed | whole run is a no-op + log |
| Lock held / kill switch | no-op + log |
| Network/sheet error | abort run, alert, retry next schedule |

## 7. Observability

- Append a structured line per attempt to `creds/run_logs/autoexec.*`.
- Completion webhook summary every run (reuse the notify config).
- Optional `GUI_QUEUE.STATUS` writeback for at-a-glance sheet view.

## 8. Config (env)

`RSA_AUTO_BROKERS`, `RSA_AUTO_MAX_PLAYS`, `RSA_AUTO_MAX_ACCOUNTS`,
`RSA_AUTO_MAX_RETRIES`, `RSA_AUTO_DISABLED`, `RSA_AUTO_NOTIFY_URL`,
plus the producer's `RSA_SHEETS_*` and the engine's broker creds.

## 9. Rollout phases

1. **Shadow (no orders)** — scheduled dry runs for ≥1–2 weeks; compare
   selected plays vs. the Apps Script feed and vs. `hist_alerts_v1`
   outcomes. Zero money risk.
2. **One broker, capped, market-hours** — Fidelity only,
   `MAX_PLAYS=1`, `MAX_ACCOUNTS` small, after M1 is live-validated and
   the after-hours issue is moot (market-hours gate). Watch alerts.
3. **Widen** caps/brokers only after a clean track record.

## 10. Prerequisites (gates before building/enabling)

- [ ] M1 live-validated in market hours (filter + fill + no-double-buy).
- [ ] Corpus guards green with measured precision (esp. false-ROUND_UP
      rate from `hist_alerts_v1`).
- [ ] Unattended-2FA strategy chosen for the first broker.
- [ ] Notification channel configured.

## 11. Open decisions for review

1. Unattended-2FA approach per broker (§5).
2. First eligible broker + initial caps.
3. Market-hours-only — agree this is mandatory (sidesteps after-hours)?
4. `GUI_QUEUE.STATUS` writeback — yes/no (cosmetic).
5. Kill-switch mechanism — flag file vs. env vs. a sheet cell.
6. Notification channel + how loud (every run vs. only on action/error).

Nothing here changes the manual M4 path, which remains the safe default.
