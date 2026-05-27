"""Embedded public key for license-token verification.

The corresponding private key is held by the operator off-machine
(YubiKey / 1Password / sealed envelope) and signs the activation
endpoint's responses. The private key never lives in this repo, on
the Cloudflare Worker, or anywhere reachable from a running install.

To replace the placeholder with a real key for a real build:

1.  Generate the keypair on a trusted machine (one-time, never again):

        python -c "from cryptography.hazmat.primitives.asymmetric.ed25519 \
import Ed25519PrivateKey; \
import base64; \
k = Ed25519PrivateKey.generate(); \
priv = k.private_bytes_raw(); \
pub = k.public_key().public_bytes_raw(); \
print('PRIVATE (store offline, NEVER commit):', base64.b64encode(priv).decode()); \
print('PUBLIC (paste into _keys.py):', base64.b64encode(pub).decode())"

2.  Store the PRIVATE half in a password manager / hardware token.

3.  Paste the PUBLIC half (32 bytes base64) into ``PUBLIC_KEY_B64`` below.

4.  Commit the public-key change. Rebuild and ship.

While ``PUBLIC_KEY_B64`` is empty, the verifier rejects every token
(``current_tier()`` returns ``"unlicensed"``). This is the correct
fail-safe: an unconfigured build cannot accidentally unlock tiers.
"""

from __future__ import annotations

# Production Ed25519 public key, base64-encoded raw 32 bytes.
# EMPTY by default — verifier returns False until this is filled in.
PUBLIC_KEY_B64: str = ""

# Cloudflare Worker activation endpoint. Filled in once the worker
# is deployed (Phase 3 of the build). Currently a placeholder; the
# client module returns a clear error if used while empty.
ACTIVATION_URL: str = ""
