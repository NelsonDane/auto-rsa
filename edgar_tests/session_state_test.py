"""Session-health audit: classification, TTL config, persistence."""

import os
import time
from datetime import UTC, datetime, timedelta

import pytest

from src import session_state as ss


@pytest.fixture(autouse=True)
def _tmp(tmp_path, monkeypatch):
    creds = tmp_path / "creds"
    creds.mkdir()
    monkeypatch.setattr(ss, "_CREDS", creds)
    monkeypatch.setattr(ss, "_DB_PATH", creds / "sessions.db")
    monkeypatch.setattr(ss, "_last_order_at", lambda _b: None)
    monkeypatch.delenv("RSA_SESSION_TTL_DAYS", raising=False)
    monkeypatch.delenv("RSA_SESSION_TTL_OVERRIDES", raising=False)
    return creds


def _by_broker(records):
    out = {}
    for r in records:
        out.setdefault(r.broker, []).append(r)
    return out


def _age_file(path, days):
    old = time.time() - days * 86400
    os.utime(path, (old, old))


def test_stateless_ephemeral_unknown(_tmp):
    recs = _by_broker(ss.audit(persist=False))
    assert recs["fennel"][0].health == ss.GREEN          # token, no file
    assert recs["public"][0].health == ss.GREEN
    assert recs["tornado"][0].health == ss.UNSUPPORTED   # no persistence
    # WF now keeps a persistent profile -> tracked; RED until first login.
    assert recs["wellsfargo"][0].health == ss.RED
    assert recs["vanguard"][0].health == ss.UNKNOWN        # path unconfirmed


def test_token_broker_missing_then_fresh_then_stale(_tmp):
    assert _by_broker(ss.audit(persist=False))["schwab"][0].health == ss.RED

    art = _tmp / "schwab0.json"
    art.write_text("{}")
    _age_file(art, 0)
    assert _by_broker(ss.audit(persist=False))["schwab"][0].health == ss.GREEN

    _age_file(art, 99)  # well past default 6d TTL
    rec = _by_broker(ss.audit(persist=False))["schwab"][0]
    assert rec.health == ss.RED and "TTL" in rec.reason


def test_yellow_band_and_ttl_override(_tmp, monkeypatch):
    art = _tmp / "robinhood_acct.pickle"
    art.write_text("x")
    monkeypatch.setenv("RSA_SESSION_TTL_DAYS", "10")
    _age_file(art, 8)  # 8/10 = 0.8 -> within [0.7,1) -> YELLOW
    assert _by_broker(ss.audit(persist=False))["robinhood"][0].health == ss.YELLOW
    _age_file(art, 3)  # 0.3 -> GREEN
    assert _by_broker(ss.audit(persist=False))["robinhood"][0].health == ss.GREEN
    # Per-broker override beats the global default.
    monkeypatch.setenv("RSA_SESSION_TTL_OVERRIDES", '{"robinhood": 2}')
    _age_file(art, 3)  # 3 > 2 -> RED for robinhood only
    assert ss.ttl_days("robinhood") == 2
    assert _by_broker(ss.audit(persist=False))["robinhood"][0].health == ss.RED


def test_inactivity_does_not_affect_health(_tmp, monkeypatch):
    # Domain rule: tickers are often unavailable/restricted on a broker,
    # so a long gap with no buys must NOT degrade a healthy session.
    art = _tmp / "BBAE_1.pkl"
    art.write_text("x")
    _age_file(art, 0)
    stale = (datetime.now(UTC) - timedelta(days=120)).isoformat()
    monkeypatch.setattr(ss, "_last_order_at", lambda _b: stale)
    rec = _by_broker(ss.audit(persist=False))["bbae"][0]
    assert rec.health == ss.GREEN  # liveness-only; activity is informational
    assert rec.last_order_at == stale


def test_persist_and_load_round_trip(_tmp):
    (_tmp / "Fidelity_Fidelity 1.json").write_text("{}")
    recs = ss.audit(persist=True)
    assert recs
    loaded = ss.load_last_audit()
    assert {r["broker"] for r in loaded} == {r.broker for r in recs}
    fid = [r for r in loaded if r["broker"] == "fidelity"]
    assert fid and fid[0]["health"] == ss.GREEN
