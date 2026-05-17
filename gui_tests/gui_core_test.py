"""Unit tests for the GUI core (vault, prompts, brokers_meta, runner).

These lock in the security/reliability hardening: crypto round-trip,
legacy KDF backward-compat, corrupt-file handling, the prompt threading
contract, env assembly edge cases, redaction, and the runner state
machine / single-instance lock (without spawning the real engine).
"""

from __future__ import annotations

import base64
import json
import secrets
import threading
import time

import pytest
from cryptography.fernet import Fernet

from src.gui.core import runner as runner_mod
from src.gui.core.brokers_meta import get_broker
from src.gui.core.prompts import PromptBus
from src.gui.core.results import group_by_broker, status_lines
from src.gui.core.runner import RunBusyError, RunStatus, TradeRunner
from src.gui.core.tickers import normalize_and_validate
from src.gui.core.totp import normalize_totp_secret


def test_totp_secret_validation():
    # Valid base32 (spaces/case/dashes normalized away).
    norm, err = normalize_totp_secret("jbsw y3dp ehpk 3pxp")
    assert err is None and norm == "JBSWY3DPEHPK3PXP"
    # NA / blank pass through (means "no 2FA").
    assert normalize_totp_secret("NA") == ("NA", None)
    assert normalize_totp_secret("") == ("", None)
    # Symantec VIP Credential ID -> rejected (0/1/8/9 not base32).
    n, e = normalize_totp_secret("VSMT19180001")
    assert n is None and "base32" in e
    # otpauth URI -> rejected with specific hint.
    n, e = normalize_totp_secret("otpauth://totp/x?secret=ABCD")
    assert n is None and "otpauth" in e


# --- results grouping -------------------------------------------------
def test_results_status_and_grouping():
    log = (
        "Logging in to Robinhood...\n"
        "noise that should be dropped\n"
        "Robinhood purchase complete\n"  # 'purchase' must NOT flip to Chase
        "Error: something at Robinhood\n"
    )
    assert "noise that should be dropped" not in status_lines(log)
    groups = group_by_broker(log)
    # 'purchase' contains 'chase' but \b prevents a false Chase match.
    assert "Chase" not in groups
    assert any("purchase complete" in ln for ln in groups["Robinhood"])
    assert any("Error: something" in ln for ln in groups["Robinhood"])
from src.gui.core.vault import _LEGACY_KDF, Vault, VaultError, _derive_key


# --- tickers ----------------------------------------------------------
def test_ticker_validation():
    valid, invalid = normalize_and_validate(" aapl, MSFT ,brk.b, rds-a, AAPL")
    assert valid == ["AAPL", "MSFT", "BRK.B", "RDS-A"]  # upper, dedup, order
    assert invalid == []
    valid, invalid = normalize_and_validate("AAPL, no spaces, 123, TOOLONGSYM, ;")
    assert valid == ["AAPL"]
    assert invalid == ["no spaces", "123", "TOOLONGSYM", ";"]
    assert normalize_and_validate("") == ([], [])


# --- vault ------------------------------------------------------------
def test_vault_roundtrip_and_wrong_password(tmp_path):
    v = Vault(tmp_path / "v.json")
    v.initialize("master")
    v.set_broker("robinhood", [{"username": "u", "password": "p", "totp_secret": ""}])
    v.lock()
    v2 = Vault(tmp_path / "v.json")
    with pytest.raises(VaultError):
        v2.unlock("wrong")
    v2.unlock("master")
    assert v2.get_broker_accounts("robinhood")[0]["username"] == "u"


def test_vault_build_env_single_account(tmp_path):
    v = Vault(tmp_path / "v.json")
    v.initialize("master")
    v.set_broker(
        "robinhood",
        [
            {"username": "u1", "password": "p1", "totp_secret": ""},
            {"username": "u2", "password": "p2", "totp_secret": ""},
        ],
    )
    env_var = get_broker("robinhood").env_var
    full = v.build_env(["robinhood"])[env_var]
    one = v.build_env_single_account("robinhood", 1)[env_var]
    # The single-account env carries only the second account, not both.
    assert "u2" in one
    assert "u1" not in one
    assert full != one
    # Out-of-range index yields nothing.
    assert v.build_env_single_account("robinhood", 9) == {}


def test_vault_corrupt_file_raises_vaulterror(tmp_path):
    p = tmp_path / "v.json"
    p.write_text("{ not valid json")
    with pytest.raises(VaultError):
        Vault(p).unlock("x")


def test_vault_corrupt_contents_raises_vaulterror(tmp_path):
    p = tmp_path / "v.json"
    salt = secrets.token_bytes(16)
    from src.gui.core.vault import _STRONG_KDF

    key = _derive_key("pw", salt, _STRONG_KDF)
    token = Fernet(key).encrypt(b"not json at all")
    p.write_text(
        json.dumps(
            {
                "salt": base64.b64encode(salt).decode(),
                "token": base64.b64encode(token).decode(),
                "kdf": _STRONG_KDF,
            },
        ),
    )
    with pytest.raises(VaultError):
        Vault(p).unlock("pw")


def test_vault_legacy_kdf_backward_compat(tmp_path):
    p = tmp_path / "legacy.json"
    salt = secrets.token_bytes(16)
    key = _derive_key("pw", salt, _LEGACY_KDF)
    token = Fernet(key).encrypt(json.dumps({"settings": {}, "brokers": {}}).encode())
    # No "kdf" field -> must fall back to legacy params.
    p.write_text(
        json.dumps(
            {
                "salt": base64.b64encode(salt).decode(),
                "token": base64.b64encode(token).decode(),
            },
        ),
    )
    v = Vault(p)
    v.unlock("pw")
    assert v.is_unlocked()


def test_vault_change_password_upgrades_and_reunlocks(tmp_path):
    p = tmp_path / "v.json"
    salt = secrets.token_bytes(16)
    key = _derive_key("old", salt, _LEGACY_KDF)
    token = Fernet(key).encrypt(json.dumps({"settings": {}, "brokers": {}}).encode())
    p.write_text(
        json.dumps(
            {"salt": base64.b64encode(salt).decode(), "token": base64.b64encode(token).decode()},
        ),
    )
    v = Vault(p)
    v.change_password("old", "new")
    assert json.loads(p.read_text())["kdf"]["n"] > _LEGACY_KDF["n"]
    v.lock()
    v.unlock("new")
    assert v.is_unlocked()


def test_vault_env_raw_precedence_and_secret_values(tmp_path):
    env = tmp_path / ".env"
    env.write_text('ROBINHOOD="user:p@ss:w:rd:LONGSECRET"\n')
    v = Vault(tmp_path / "v.json")
    v.initialize("pw")
    imported = v.import_env_file(env)
    assert "Robinhood" in imported
    # Raw value preserved verbatim (colons in password intact).
    assert v.build_env(["robinhood"])["ROBINHOOD"] == "user:p@ss:w:rd:LONGSECRET"
    assert "robinhood" in v.configured_broker_keys()
    assert "LONGSECRET" in v.secret_values()


def test_vault_materialize_env_restores(tmp_path, monkeypatch):
    import os

    v = Vault(tmp_path / "v.json")
    v.initialize("pw")
    v.set_broker("fennel", [{"pat": "TOKEN123456"}])
    monkeypatch.delenv("FENNEL", raising=False)
    with v.materialize_env(["fennel"]):
        assert os.environ["FENNEL"] == "TOKEN123456"
    assert "FENNEL" not in os.environ


# --- brokers_meta -----------------------------------------------------
@pytest.mark.parametrize(
    ("key", "acc", "expected"),
    [
        ("robinhood", {"username": "u", "password": "p", "totp_secret": ""}, "u:p:NA"),
        ("robinhood", {"username": "u", "password": "p", "totp_secret": "S"}, "u:p:S"),
        ("fennel", {"pat": "tok"}, "tok"),
        (
            "chase",
            {"username": "u", "password": "p", "phone_last_four": "1234", "debug": ""},
            "u:p:1234",
        ),
    ],
)
def test_brokers_meta_assembly(key, acc, expected):
    assert get_broker(key).assemble_env_value([acc]) == expected


# --- prompts ----------------------------------------------------------
def test_prompt_bus_request_response_cycle():
    pb = PromptBus()
    got: list[str] = []

    def worker() -> None:
        pb.open("Enter code:")
        got.append(pb.wait_answer())

    t = threading.Thread(target=worker)
    t.start()
    time.sleep(0.1)
    snap = pb.snapshot()
    assert snap.waiting and snap.text == "Enter code:"
    assert pb.respond("wrong-id", "x") is False  # stale id ignored
    assert pb.respond(snap.prompt_id, "123456") is True
    t.join(timeout=2)
    assert got == ["123456"]


def test_prompt_bus_cancel_unblocks():
    pb = PromptBus()
    out: list[str] = []
    t = threading.Thread(target=lambda: (pb.open("x"), out.append(pb.wait_answer())))
    t.start()
    time.sleep(0.1)
    pb.cancel()
    t.join(timeout=2)
    assert out == [""]


# --- runner -----------------------------------------------------------
def test_runner_redaction():
    r = TradeRunner(Vault())
    r._secrets = ["SUPERSECRET", "tok123"]
    assert r._redact("user logged in SUPERSECRET tok123") == "user logged in *** ***"


def test_runner_popen_failure_sets_error(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "_RUN_LOCK", tmp_path / "run.lock")
    v = Vault(tmp_path / "v.json")
    v.initialize("pw")

    def boom(*_a, **_k):
        msg = "no interpreter"
        raise OSError(msg)

    monkeypatch.setattr(runner_mod.subprocess, "Popen", boom)
    r = TradeRunner(v)
    r.start_holdings(["fennel"])
    assert r.snapshot().status == RunStatus.ERROR
    assert not r.is_running()
    assert not (tmp_path / "run.lock").exists()  # lock released


def test_runner_single_instance_lock(tmp_path, monkeypatch):
    lock = tmp_path / "run.lock"
    monkeypatch.setattr(runner_mod, "_RUN_LOCK", lock)
    # A live engine pid -> lock is held, not stale.
    import os

    lock.write_text(json.dumps({"engine_pid": os.getpid(), "created": time.time()}))
    v = Vault(tmp_path / "v.json")
    v.initialize("pw")
    with pytest.raises(RunBusyError):
        TradeRunner(v)._acquire_run_lock()
    # A dead pid -> stale -> reclaimable.
    lock.write_text(json.dumps({"engine_pid": 999999999, "created": time.time()}))
    TradeRunner(v)._acquire_run_lock()
    assert lock.exists()
