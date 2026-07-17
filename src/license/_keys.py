"""Embedded public key for license-token verification.

Model: the Cloudflare Worker SIGNS tokens (docs/CLOUDFLARE_LICENSE_BUILD.md).
The Ed25519 PRIVATE key lives ONLY as a Worker secret (``SIGNING_KEY_PEM``)
and in the operator's password manager — never in this repo, never in the
shipped binary. This file holds only the PUBLIC half, which is meant to
ship: it can verify tokens but cannot mint them.

To wire a real key for a real build (one time):

1.  Generate the keypair on your machine:

        openssl genpkey -algorithm ed25519 -out rsa-signing-key.pem

2.  Put the PRIVATE key on the Worker + in 1Password (never commit it):

        cd server/license-worker
        wrangler secret put SIGNING_KEY_PEM   # paste the file's contents

3.  Extract the raw PUBLIC key (base64) and paste it into
    ``PUBLIC_KEY_B64`` below:

        python -c "from cryptography.hazmat.primitives.serialization import \
load_pem_public_key, Encoding, PublicFormat; import base64, subprocess; \
pem = subprocess.run(['openssl','pkey','-in','rsa-signing-key.pem','-pubout'], \
capture_output=True, check=True).stdout; \
pub = load_pem_public_key(pem); \
print(base64.b64encode(pub.public_bytes(Encoding.Raw, PublicFormat.Raw)).decode())"

4.  Set ``ACTIVATION_URL`` to your deployed Worker URL. Commit both
    constants (public key + URL are not secret). Rebuild and ship.

The JS<->Python signature contract is locked by golden vectors on both
sides (server/license-worker/golden/golden.mjs and
edgar_tests/license_golden_test.py) — run them before every deploy.

While ``PUBLIC_KEY_B64`` is empty, the verifier rejects every token
(``current_tier()`` returns ``"unlicensed"``). This is the correct
fail-safe: an unconfigured build cannot accidentally unlock tiers.
"""

from __future__ import annotations

# Production Ed25519 public key, base64-encoded raw 32 bytes.
# EMPTY by default — verifier returns False until this is filled in.
PUBLIC_KEY_B64: str = "KUrOISB4NH8EBY0wLsWGWlhHlUHpCIXEYrRi1PgU7dE="

# Cloudflare Worker activation endpoint. Filled in once the worker
# is deployed (Phase 3 of the build). Currently a placeholder; the
# client module returns a clear error if used while empty.
ACTIVATION_URL: str = "https://rsa-license.ralanleder.workers.dev"
