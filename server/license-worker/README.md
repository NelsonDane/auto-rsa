# auto-rsa license Worker — deploy runbook

This Worker signs short-lived license tokens the desktop app verifies,
and serves the remote **kill switch**. The signing model is
**Worker-signs** (see `docs/CLOUDFLARE_LICENSE_BUILD.md`): the Ed25519
private key lives only as a Worker secret + in your password manager.

Everything below runs **on your machine** (needs `wrangler`, which the
in-app connector can't do). The account already has the `rsa-license`
Worker (placeholder) and the `rsa_licenses` KV namespace (id baked into
`wrangler.toml`).

## One-time setup

Prereqs: **Node.js** (for wrangler) and **Python with `cryptography`**
(the app already has it). No OpenSSL needed.

```bash
# 0. From this directory
cd server/license-worker
npm install                      # installs wrangler locally
npx wrangler login               # authorize wrangler to your Cloudflare account

# 1. Generate keys (writes rsa-signing-key.pem, prints PUBLIC_KEY_B64 + ADMIN_SECRET)
python gen-keys.py
#    -> copy the PUBLIC_KEY_B64 and ADMIN_SECRET it prints. The .pem stays
#       here (gitignored) + your password manager. NEVER commit the .pem.

# 2. Put the two secrets on the Worker (paste when prompted)
npx wrangler secret put SIGNING_KEY_PEM     # paste the FULL contents of rsa-signing-key.pem
npx wrangler secret put ADMIN_SECRET        # paste the ADMIN_SECRET from step 1

# 3. Put the PUBLIC key + (after deploy) the URL into the app
#    -> paste PUBLIC_KEY_B64 into src/license/_keys.py

# 4. Prove the crypto BEFORE deploying (both must be green)
npm run test:golden
( cd ../.. && python -m pytest edgar_tests/license_golden_test.py -q )

# 5. Deploy
npm run deploy
#    -> note the URL, e.g. https://rsa-license.<subdomain>.workers.dev
#    -> set ACTIVATION_URL to that URL in src/license/_keys.py, then commit
#       _keys.py (public key + URL are NOT secret; the .pem is).
```

## Generate keys without a terminal — the web console

Open **`https://rsa-license.<subdomain>.workers.dev/admin`** in any browser
(laptop or phone). Paste your `ADMIN_SECRET` once (it's kept only in your
browser — tick "Remember on this device" to persist it locally), then:

- **Generate a key**: pick the type from a dropdown (Friend — Main, Friend —
  Lite, Operator, Advanced, Basic), add an optional note (who it's for) and an
  optional expiry, and click **Generate**. The key appears with a Copy button —
  hand it to your friend, who pastes it into the app's **License** section.
- **Existing licenses**: list them, see how many machines have activated each
  key (with a **⚠ churn** flag when a key looks shared), **Unbind** one (so the
  friend can re-activate the same key on a new computer), and **Revoke** any.
- **Recent activity**: a feed of the anonymous diagnostics friends' apps report
  (app version, coarse error category, run counts). No account or trade data.
- **Kill switch**: turn the emergency stop on/off (optionally only for builds
  at or below a version).

The page carries no secret and no signing code — every action it fires still
requires the `ADMIN_SECRET` on the `/admin/*` API — so nothing sensitive is
exposed by serving it. The dropdown also removes the #1 manual error: a
mistyped tier string. (You must redeploy the Worker once — `npm run deploy`,
or via the Cloudflare dashboard — to publish the `/admin` page.)

## Operating it from a terminal (alternative)

```bash
export RSA_LICENSE_SERVER_URL="https://rsa-license.<subdomain>.workers.dev"
export RSA_LICENSE_ADMIN_SECRET="<the ADMIN_SECRET you set>"

python admin/rsa_license.py issue --tier operator --for "operator (self)"
python admin/rsa_license.py issue --tier advanced --for "Alice"
python admin/rsa_license.py list
python admin/rsa_license.py revoke <license_id>

# The emergency stop for a crucial bug:
python admin/rsa_license.py kill on --message "Paused: fixing a fill bug — update coming"
python admin/rsa_license.py kill on --min-version 0.8.0   # only kill buggy builds
python admin/rsa_license.py kill off
```

## Smoke test after deploy

```bash
curl https://rsa-license.<subdomain>.workers.dev/killswitch
# -> {"active":false,"message":"","min_app_version":""}

# issue -> activate is exercised by the app's License section; or by hand:
curl -X POST .../activate -H 'content-type: application/json' \
  -d '{"license_key":"rsa-...","hardware_id":"h_test","app_version":"2.1.0"}'
# -> {"payload":{...},"signature":"...","account_cap":5}
```

## Safety notes

- `test/test_signing_key.pem` is a **throwaway golden-vector fixture**,
  not your production key. Your real key is `rsa-signing-key.pem`, which
  is `.gitignore`d and only ever on your machine + the Worker secret.
- Never commit `.dev.vars` (wrangler local secrets) — it's gitignored.
- If the production private key ever leaks: generate a new keypair,
  `wrangler secret put SIGNING_KEY_PEM` the new one, update
  `PUBLIC_KEY_B64`, reship the app, re-issue licenses.
- The kill switch is **fail-open** in the client on a network error
  (a Cloudflare blip never freezes a friend). Pair `kill` with `revoke`
  for a hard, grace-proof stop of a single license.
