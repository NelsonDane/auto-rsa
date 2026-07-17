"""Golden-vector test (Python side): the shipped verify.py accepts a token
produced by the Worker's signer.

Pairs with server/license-worker/golden/golden.mjs (the JS side). Together
they lock the cross-language Ed25519 + canonical-JSON contract: the same
checked-in vector is signed in JS and verified here in Python. If either
side changes canonicalization, one of these two tests breaks loudly
before a deploy can strand every friend's activation.

The key material here is a THROWAWAY test key committed under
server/license-worker/golden/ — never the production signing key.
"""

import json
from pathlib import Path

from src.license import verify

_GOLDEN = (
    Path(__file__).resolve().parents[1]
    / "server" / "license-worker" / "golden" / "golden.json"
)


def _load() -> dict:
    return json.loads(_GOLDEN.read_text())


def test_golden_token_verifies_against_verify_py():
    g = _load()
    token = {"payload": g["payload"], "signature": g["signature"]}
    assert verify.verify_token(token, g["public_key_b64"]) is True


def test_tampered_payload_is_rejected():
    g = _load()
    bad_payload = dict(g["payload"])
    bad_payload["tier"] = "operator"  # privilege bump must not verify
    token = {"payload": bad_payload, "signature": g["signature"]}
    assert verify.verify_token(token, g["public_key_b64"]) is False


def test_bitflipped_signature_is_rejected():
    g = _load()
    sig = g["signature"]
    flipped = sig[:-2] + ("AA" if not sig.endswith("AA") else "BB")
    token = {"payload": g["payload"], "signature": flipped}
    assert verify.verify_token(token, g["public_key_b64"]) is False


def test_canonical_form_matches_verify_py():
    """The signed bytes are exactly verify.py's canonical_bytes — sorted
    keys, no whitespace — so a re-canonicalization can't silently break
    verification."""
    g = _load()
    canon = verify.canonical_bytes(g["payload"]).decode("utf-8")
    assert " " not in canon
    assert canon.index('"expires_at"') < canon.index('"tier"')
