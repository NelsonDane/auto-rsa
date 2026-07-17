"""telemetry: privacy-safe operator beacon — gating, sanitization, no leaks."""

import pytest

from src.license import telemetry


@pytest.fixture(autouse=True)
def _base(monkeypatch):
    monkeypatch.delenv("RSA_TELEMETRY", raising=False)
    # A configured server so enabled() isn't gated on that in most tests.
    monkeypatch.setattr(telemetry.client, "server_url", lambda: "https://x.test")
    yield


def test_disabled_by_default_in_pro_build(monkeypatch):
    monkeypatch.setattr(telemetry._keys, "REQUIRE_LICENSE_TO_TRADE", False)
    assert telemetry.enabled() is False


def test_enabled_in_friend_build(monkeypatch):
    monkeypatch.setattr(telemetry._keys, "REQUIRE_LICENSE_TO_TRADE", True)
    assert telemetry.enabled() is True


def test_env_override_off_and_on(monkeypatch):
    monkeypatch.setattr(telemetry._keys, "REQUIRE_LICENSE_TO_TRADE", True)
    monkeypatch.setenv("RSA_TELEMETRY", "0")
    assert telemetry.enabled() is False
    monkeypatch.setattr(telemetry._keys, "REQUIRE_LICENSE_TO_TRADE", False)
    monkeypatch.setenv("RSA_TELEMETRY", "1")
    assert telemetry.enabled() is True


def test_disabled_without_a_server(monkeypatch):
    monkeypatch.setattr(telemetry._keys, "REQUIRE_LICENSE_TO_TRADE", True)
    monkeypatch.setattr(telemetry.client, "server_url", lambda: "")
    assert telemetry.enabled() is False


def test_clean_counts_drops_unknown_and_nonint():
    c = telemetry._clean_counts(
        {"brokers": 3, "errors": 2, "cap_blocks": 1, "secret": "x", "f": 1.5, "b": True, "neg": -3},
    )
    assert c == {"brokers": 3, "errors": 2, "cap_blocks": 1}


def test_report_is_a_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(telemetry._keys, "REQUIRE_LICENSE_TO_TRADE", False)
    called = {"n": 0}
    monkeypatch.setattr(telemetry, "_send", lambda *a, **k: called.__setitem__("n", 1))
    telemetry.report("run_finished", counts={"brokers": 1})
    assert called["n"] == 0


def test_send_payload_carries_no_account_or_trade_data(monkeypatch):
    monkeypatch.setattr(
        telemetry.token_store, "load",
        lambda: {"payload": {"license_id": "L"}, "signature": "s"},
    )
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return type("R", (), {})()

    monkeypatch.setattr(telemetry.requests, "post", fake_post)
    telemetry._send("run_error", "failed", "broker_errors", {"brokers": 2, "errors": 1, "acct": "secret"})

    body = captured["json"]
    assert captured["url"].endswith("/telemetry")
    assert body["token"] == {"payload": {"license_id": "L"}, "signature": "s"}
    assert body["event"] == "run_error"
    assert body["category"] == "broker_errors"
    assert body["counts"] == {"brokers": 2, "errors": 1}  # 'acct' dropped
    # Hard assertion: nothing account/credential/holdings/ticker-ish anywhere.
    leaky = {"account", "credentials", "holdings", "ticker", "amount", "password", "acct", "vault"}
    assert not (set(body) & leaky)
    assert not (set(body["counts"]) & leaky)


def test_free_text_category_is_dropped(monkeypatch):
    monkeypatch.setattr(telemetry.token_store, "load", lambda: {"payload": {}, "signature": "s"})
    captured = {}
    monkeypatch.setattr(
        telemetry.requests, "post",
        lambda url, json=None, timeout=None: captured.update(json=json) or type("R", (), {})(),
    )
    # A call site tries to sneak identifying text through 'category'.
    telemetry._send("x", "", "AAPL bought 5 shares in acct 1234", {})
    assert captured["json"]["category"] == ""  # not in the fixed vocab -> dropped
