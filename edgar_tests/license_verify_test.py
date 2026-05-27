"""Signature verification + canonicalization: golden vectors + tamper."""

from __future__ import annotations

import json

import pytest

from src.license import verify
from edgar_tests.license_test_helpers import (
    public_key_b64,
    sign_token,
)


@pytest.fixture
def pub() -> str:
    return public_key_b64()


def test_canonical_is_sorted_separated_and_utf8_safe():
    # Different key order + whitespace must collapse to the same bytes.
    a = verify.canonical_bytes({"b": 1, "a": 2, "c": ["x", "ünïcode"]})
    b = verify.canonical_bytes({"c": ["x", "ünïcode"], "a": 2, "b": 1})
    assert a == b
    assert a == b'{"a":2,"b":1,"c":["x","\xc3\xbcn\xc3\xafcode"]}'


def test_signed_token_verifies(pub):
    token = sign_token({"x": 1, "y": "hello"})
    assert verify.verify_token(token, pub)


def test_payload_tampering_fails(pub):
    token = sign_token({"tier": "advanced", "n": 1})
    token["payload"]["tier"] = "operator"  # tamper after signing
    assert not verify.verify_token(token, pub)


def test_signature_tampering_fails(pub):
    token = sign_token({"x": 1})
    sig = token["signature"]
    # Flip one base64 char (must stay valid base64url).
    flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
    token["signature"] = flipped
    assert not verify.verify_token(token, pub)


def test_wrong_public_key_fails():
    token = sign_token({"x": 1})
    other_key = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="  # 32 zero bytes
    assert not verify.verify_token(token, other_key)


def test_empty_public_key_fails():
    token = sign_token({"x": 1})
    assert not verify.verify_token(token, "")


@pytest.mark.parametrize("bad", [
    {},
    {"payload": "not a dict", "signature": "abc"},
    {"payload": {"x": 1}, "signature": 42},
    {"payload": {"x": 1}, "signature": "!!!not-b64!!!"},
])
def test_malformed_tokens_return_false_not_raise(pub, bad):
    assert verify.verify_token(bad, pub) is False


def test_roundtrip_via_json_disk_form(pub, tmp_path):
    # The on-disk form is JSON.dumps(token) — ensure the canonicalisation
    # survives a load/dump cycle (the disk pretty-prints with indent=2).
    token = sign_token({"a": [1, 2, 3], "b": {"nested": True}})
    p = tmp_path / "tok.json"
    p.write_text(json.dumps(token, indent=2), encoding="utf-8")
    reloaded = json.loads(p.read_text(encoding="utf-8"))
    assert verify.verify_token(reloaded, pub)
