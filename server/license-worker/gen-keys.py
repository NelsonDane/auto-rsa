#!/usr/bin/env python3
"""One-command keygen for the license Worker (cross-platform, no OpenSSL).

Run once, on your machine:

    python server/license-worker/gen-keys.py

It:
  1. generates the Ed25519 signing keypair,
  2. writes the PRIVATE key to rsa-signing-key.pem (gitignored),
  3. generates an ADMIN_SECRET,
  4. prints the PUBLIC key (paste into src/license/_keys.py) and the
     exact next commands.

The private key never leaves this folder + the Worker secret. It refuses
to overwrite an existing key (pass --force only if you truly mean to
rotate — that invalidates every already-issued license).
"""

from __future__ import annotations

import base64
import secrets
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

HERE = Path(__file__).resolve().parent
KEY_PATH = HERE / "rsa-signing-key.pem"


def main(argv: list[str]) -> int:
    force = "--force" in argv
    if KEY_PATH.exists() and not force:
        print(f"Refusing to overwrite {KEY_PATH.name} (it already exists).")
        print("That key is bound to every license you've issued. Only pass")
        print("--force if you intend to ROTATE (which invalidates them all).")
        return 1

    priv = Ed25519PrivateKey.generate()
    pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    KEY_PATH.write_bytes(pem)
    # Best-effort tighten perms (POSIX; a no-op on Windows).
    try:
        KEY_PATH.chmod(0o600)
    except OSError:
        pass

    pub_b64 = base64.b64encode(
        priv.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        ),
    ).decode()
    admin_secret = "rsa_admin_" + secrets.token_urlsafe(32)

    print("=" * 68)
    print("Keypair generated.")
    print("=" * 68)
    print(f"\nPRIVATE key written to: {KEY_PATH}")
    print("  -> stays on this machine + the Worker secret. NEVER commit it.")
    print("  -> back it up in your password manager.\n")
    print("PUBLIC_KEY_B64 (paste into src/license/_keys.py):")
    print(f"\n    {pub_b64}\n")
    print("ADMIN_SECRET (save in your password manager — you'll paste it twice):")
    print(f"\n    {admin_secret}\n")
    print("Next, from server/license-worker/ :")
    print("  npx wrangler secret put SIGNING_KEY_PEM   # paste rsa-signing-key.pem contents")
    print("  npx wrangler secret put ADMIN_SECRET      # paste the ADMIN_SECRET above")
    print("  npm run test:golden                       # must be green")
    print("  npm run deploy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
