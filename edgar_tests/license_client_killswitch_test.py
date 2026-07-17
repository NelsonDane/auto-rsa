"""client.order_placement_blocked / refresh_now — the kill-switch gate.

The pre-trade gate MUST fail OPEN: a network blip or an unconfigured
server can never freeze a legitimate run (revoke is the hard backstop).
"""

import pytest

from src.license import client


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    client._kill_cache["ts"] = 0.0
    client._kill_cache["value"] = None
    monkeypatch.setattr(client, "server_url", lambda: "https://example.test")
    yield
    client._kill_cache["ts"] = 0.0
    client._kill_cache["value"] = None


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


def test_killswitch_active_blocks(monkeypatch):
    monkeypatch.setattr(
        client.requests, "get",
        lambda *a, **k: _Resp(200, {"active": True, "message": "stop"}),
    )
    assert client.order_placement_blocked() == (True, "stop")


def test_killswitch_inactive_allows(monkeypatch):
    monkeypatch.setattr(
        client.requests, "get", lambda *a, **k: _Resp(200, {"active": False}),
    )
    assert client.order_placement_blocked() == (False, "")


def test_network_error_fails_open(monkeypatch):
    def boom(*a, **k):
        raise client.requests.RequestException("no net")

    monkeypatch.setattr(client.requests, "get", boom)
    # Unreachable server -> NOT blocked (fail open).
    assert client.order_placement_blocked() == (False, "")


def test_no_server_configured_allows(monkeypatch):
    monkeypatch.setattr(client, "server_url", lambda: "")
    assert client.order_placement_blocked() == (False, "")


def test_killswitch_result_is_cached(monkeypatch):
    calls = {"n": 0}

    def counting(*a, **k):
        calls["n"] += 1
        return _Resp(200, {"active": False})

    monkeypatch.setattr(client.requests, "get", counting)
    client.killswitch_status()
    client.killswitch_status()
    assert calls["n"] == 1  # second call served from the 60s cache


def test_refresh_now_requires_server(monkeypatch):
    monkeypatch.setattr(client, "server_url", lambda: "")
    ok, msg = client.refresh_now()
    assert ok is False
    assert "server" in msg.lower()


def test_refresh_now_requires_token(monkeypatch):
    monkeypatch.setattr(client.token_store, "load", lambda: None)
    ok, msg = client.refresh_now()
    assert ok is False
    assert "activate" in msg.lower()
