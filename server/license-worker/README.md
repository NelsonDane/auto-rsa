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

```bash
# 0. From this directory
cd server/license-worker
npm install                      # installs wrangler locally
npx wrangler login               # authorize wrangler to your Cloudflare account

# 1. Generate the Ed25519 signing keypair (ON YOUR MACHINE, once)
openssl genpkey -algorithm ed25519 -out rsa-signing-key.pem
#    -> back this file up in 1Password. NEVER commit it. It is .gitignored.

# 2. Put the PRIVATE key + an admin secret on the Worker as secrets
npx wrangler secret put SIGNING_KEY_PEM     # paste the whole rsa-signing-key.pem
python -c "import secrets;print('rsa_admin_'+secrets.token_urlsafe(32))"   # make one
npx wrangler secret put ADMIN_SECRET        # paste that value

# 3. Extract the PUBLIC key and put it in the app (src/license/_keys.py)
python -c "from cryptography.hazmat.primitives.serialization import load_pem_public_key,Encoding,PublicFormat;import base64,subprocess;pem=subprocess.run(['openssl','pkey','-in','rsa-signing-key.pem','-pubout'],capture_output=True,check=True).stdout;print(base64.b64encode(load_pem_public_key(pem).public_bytes(Encoding.Raw,PublicFormat.Raw)).decode())"
#    -> paste the printed string into PUBLIC_KEY_B64 in src/license/_keys.py

# 4. Prove the crypto BEFORE deploying (JS + Python must both be green)
npm run test:golden
( cd ../.. && .venv/bin/python -m pytest edgar_tests/license_golden_test.py -q )

# 5. Deploy
npm run deploy
#    -> note the URL, e.g. https://rsa-license.<subdomain>.workers.dev
#    -> put that URL in ACTIVATION_URL in src/license/_keys.py, then commit
#       _keys.py (public key + URL are NOT secret).
```

## Operating it (from the repo root)

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
