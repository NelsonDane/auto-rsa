"""client.pre_trade_block — the authoritative kill / revoke / license gate.

A live /refresh answers all three: 200 valid, 410 revoked/expired, 423
killed. Fails OPEN on network/unconfigured so a blip never freezes a run.
"""

import pytest

from src.license import client


@pytest.fixture(autouse=True)
def _server(monkeypatch):
    monkeypatch.setattr(client, "server_url", lambda: "https://example.test")
    # Default: a locally-VALID token so the SEC-5 local check passes and the
    # network path (kill/revoke) is exercised. Tests override as needed.
    monkeypatch.setattr("src.license.current_tier", lambda: "friend_main")
    client._kill_cache["ts"] = 0.0
    client._kill_cache["value"] = None
    yield
    client._kill_cache["ts"] = 0.0
    client._kill_cache["value"] = None


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


def _has_token(monkeypatch):
    monkeypatch.setattr(client.token_store, "load", lambda: {"payload": {}, "signature": "s"})


def test_valid_refresh_allows_and_saves(monkeypatch):
    _has_token(monkeypatch)
    saved = {}
    monkeypatch.setattr(client.requests, "post", lambda *a, **k: _Resp(200, {"payload": {}, "signature": "s2"}))
    monkeypatch.setattr(client.verify, "verify_token", lambda *a, **k: True)
    monkeypatch.setattr(client, "_hardware_matches", lambda t: True)
    monkeypatch.setattr(client.token_store, "save", lambda t: saved.update(t))
    assert client.pre_trade_block(require_license=True) == (False, "")
    assert saved  # token rotated


def test_revoked_blocks_and_clears(monkeypatch):
    _has_token(monkeypatch)
    cleared = {"n": 0}
    monkeypatch.setattr(client.requests, "post", lambda *a, **k: _Resp(410))
    monkeypatch.setattr(client.token_store, "clear", lambda: cleared.update(n=1))
    blocked, msg = client.pre_trade_block(require_license=True)
    assert blocked is True
    assert "revoked" in msg.lower()
    assert cleared["n"] == 1


def test_killed_blocks(monkeypatch):
    _has_token(monkeypatch)
    monkeypatch.setattr(client.requests, "post", lambda *a, **k: _Resp(423, {"message": "Paused: bug"}))
    blocked, msg = client.pre_trade_block(require_license=True)
    assert blocked is True
    assert "Paused: bug" in msg


def test_network_error_fails_open(monkeypatch):
    _has_token(monkeypatch)

    def boom(*a, **k):
        raise client.requests.RequestException("no net")

    monkeypatch.setattr(client.requests, "post", boom)
    assert client.pre_trade_block(require_license=True) == (False, "")


def test_no_token_friend_build_blocks(monkeypatch):
    monkeypatch.setattr(client.token_store, "load", lambda: None)
    blocked, msg = client.pre_trade_block(require_license=True)
    assert blocked is True
    assert "activate" in msg.lower()


def test_no_token_pro_build_only_kill_gates(monkeypatch):
    monkeypatch.setattr(client.token_store, "load", lambda: None)
    # Pro build (require_license=False): unlicensed can still trade; only
    # the kill switch blocks. Kill inactive -> allowed.
    monkeypatch.setattr(client.requests, "get", lambda *a, **k: _Resp(200, {"active": False}))
    assert client.pre_trade_block(require_license=False) == (False, "")


def test_unconfigured_server_fails_open(monkeypatch):
    monkeypatch.setattr(client, "server_url", lambda: "")
    assert client.pre_trade_block(require_license=True) == (False, "")


def test_locally_invalid_token_blocks_offline_friend_build(monkeypatch):
    # SEC-5: an expired/tampered token drops to "unlicensed" locally and
    # must fail CLOSED WITHOUT any network round-trip (offline-safe).
    monkeypatch.setattr("src.license.current_tier", lambda: "unlicensed")

    def _no_net(*_a, **_k):
        raise AssertionError("must not hit the network for a locally-invalid token")

    monkeypatch.setattr(client.requests, "post", _no_net)
    blocked, msg = client.pre_trade_block(require_license=True)
    assert blocked is True
    assert "license" in msg.lower()


def test_local_check_skipped_in_pro_build(monkeypatch):
    # Pro build (require_license=False) must NOT apply the local
    # unlicensed→block rule (its unlicensed "try one broker" flow stands).
    monkeypatch.setattr("src.license.current_tier", lambda: "unlicensed")
    monkeypatch.setattr(client.token_store, "load", lambda: None)
    monkeypatch.setattr(client.requests, "get", lambda *a, **k: _Resp(200, {"active": False}))
    assert client.pre_trade_block(require_license=False) == (False, "")
