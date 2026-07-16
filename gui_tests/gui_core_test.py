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
    # Regression: secrets whose length isn't a multiple of 8 are valid —
    # pyotp pads them at runtime. The validator must accept them too
    # (it used to reject the common 20- and 26-char keys as "invalid").
    import pyotp  # noqa: PLC0415

    for secret in ("GEZDGNBVGY3TQOJQGEZA", "NB2W45DFOIZA", "JBSWY3DPEHPK3PXPGEZDGNBVGY"):
        norm, err = normalize_totp_secret(secret)
        assert err is None and norm == secret, secret
        # And what we accept, pyotp must actually be able to consume.
        assert pyotp.TOTP(norm).now()


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


def test_runner_redaction_skips_short_numeric_secret():
    """A short all-numeric secret (a 4-digit PIN) must NOT be redacted —
    blind-replacing it corrupted unrelated numbers in the audit log
    (e.g. a balance like $1234.00)."""
    r = TradeRunner(Vault())
    r._secrets = ["1234", "12345678"]  # PIN (skip) + account number (redact)
    out = r._redact("Total: $1234.00 acct 12345678 bought 1234 shares")
    assert "$1234.00" in out  # balance untouched (PIN not redacted)
    assert "1234 shares" in out  # PIN occurrence untouched
    assert "12345678" not in out  # long numeric secret still masked
    assert out.count("***") == 1  # only the account number


def test_runner_lock_not_stale_while_owner_alive(tmp_path, monkeypatch):
    """A lock with no engine pid yet but a LIVE owner (GUI) process is
    not stale — and a dead owner makes it stale immediately, closing the
    6-hour wedge window."""
    import os

    monkeypatch.setattr(runner_mod, "_RUN_LOCK", tmp_path / "run.lock")
    # Owner alive, no engine pid -> held (not stale).
    (tmp_path / "run.lock").write_text(
        json.dumps({"engine_pid": None, "owner_pid": os.getpid(),
                    "created": 0}),  # created long ago; age check must NOT apply
    )
    assert runner_mod.TradeRunner._lock_is_stale() is False
    # Owner gone -> stale immediately despite a recent created time.
    (tmp_path / "run.lock").write_text(
        json.dumps({"engine_pid": None, "owner_pid": 2_147_483_000,
                    "created": time.time()}),
    )
    assert runner_mod.TradeRunner._lock_is_stale() is True


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


class _FakeExitedProc:
    """A subprocess whose main has exited (poll != None) but whose
    stdout pipe is still 'open' (a leaked browser child would hold it),
    simulating the wedged-reader state."""

    def __init__(self, returncode=0):
        self.returncode = returncode
        self.pid = 999_999_999  # a pid that won't exist
        self.stdout_closed = False

        class _Stdout:
            def close(_self):  # noqa: N805
                self.stdout_closed = True

        self.stdout = _Stdout()

    def poll(self):
        return self.returncode  # non-None => engine has exited


def test_reaper_recovers_wedged_running_status(tmp_path, monkeypatch):
    """A RUNNING status whose engine has exited (but whose reader is
    wedged on a leaked pipe) must self-heal to a terminal state so the
    UI's Execute/Confirm buttons re-enable. Regression for 'the tool
    won't let me proceed into live trading'."""
    monkeypatch.setattr(runner_mod, "_RUN_LOCK", tmp_path / "run.lock")
    (tmp_path / "run.lock").write_text(
        json.dumps({"engine_pid": None, "owner_pid": 1, "created": time.time()}),
    )
    v = Vault(tmp_path / "v.json")
    v.initialize("pw")
    r = TradeRunner(v)
    # Force the wedged state: status RUNNING, engine proc exited, no
    # live reader thread. Age the engine-exit marker past the grace
    # period so recovery is immediate (the grace only exists to let a
    # healthy pump's own finally win the sub-second race — see the
    # dedicated grace test below).
    r._status = RunStatus.RUNNING
    r._proc = _FakeExitedProc(returncode=0)
    r._thread = None
    r._engine_exit_seen = time.monotonic() - 10

    # is_running() must self-heal and report False.
    assert r.is_running() is False
    assert r.snapshot().status == RunStatus.FINISHED
    assert not (tmp_path / "run.lock").exists()  # lock released
    assert r._proc.stdout_closed  # reader nudged to unblock


def test_reaper_leaves_live_run_alone(tmp_path, monkeypatch):
    """A genuinely-alive engine (poll() is None) must NOT be reaped."""
    monkeypatch.setattr(runner_mod, "_RUN_LOCK", tmp_path / "run.lock")
    v = Vault(tmp_path / "v.json")
    v.initialize("pw")
    r = TradeRunner(v)

    class _AliveProc:
        pid = 999_999_998
        stdout = None

        def poll(self):
            return None  # still running

    r._status = RunStatus.RUNNING
    r._proc = _AliveProc()
    r._thread = None
    assert r.is_running() is True
    assert r.snapshot().status == RunStatus.RUNNING


def test_reaper_recovers_even_when_reader_thread_alive(tmp_path, monkeypatch):
    """The *real* wedge: the pump reader thread is ALIVE but blocked
    forever on a leaked browser's pipe (closing it from another thread
    does not interrupt a blocked read, and the browser may be
    re-parented beyond our reach). Recovery must therefore NOT wait on
    the reader — it must finalize on the engine having exited alone.

    Regression for 'I typed EXECUTE but the Confirm LIVE order button is
    not selectable' / 'Cancel does not let me place a new order': an
    earlier reaper gated recovery on ``not thread.is_alive()`` and so
    left the run wedged on RUNNING indefinitely, disabling every button.
    """
    monkeypatch.setattr(runner_mod, "_RUN_LOCK", tmp_path / "run.lock")
    (tmp_path / "run.lock").write_text(
        json.dumps({"engine_pid": None, "owner_pid": 1, "created": time.time()}),
    )
    v = Vault(tmp_path / "v.json")
    v.initialize("pw")
    r = TradeRunner(v)
    monkeypatch.setattr(r, "_write_audit_log", lambda _s: None)
    monkeypatch.setattr(r, "_notify", lambda _s: None)

    blocked = threading.Event()  # never set -> the "reader" stays alive
    reader = threading.Thread(target=blocked.wait, daemon=True)
    reader.start()
    try:
        r._status = RunStatus.RUNNING
        r._proc = _FakeExitedProc(returncode=0)
        r._thread = reader
        r._engine_exit_seen = time.monotonic() - 10  # past the grace
        assert reader.is_alive()  # precondition: reader is wedged alive

        # Must self-heal despite the still-alive reader thread.
        assert r.is_running() is False
        assert r.snapshot().status == RunStatus.FINISHED
        assert not (tmp_path / "run.lock").exists()  # lock released
        assert r._proc.stdout_closed  # reader nudged (best-effort)
    finally:
        blocked.set()


def test_cancel_finalizes_when_reader_wedged(tmp_path, monkeypatch):
    """Cancel must move a wedged run to CANCELLED immediately — even
    when the engine already exited and the reader is stuck alive on a
    leaked pipe — so the operator can always clear it and place a new
    order without waiting on a dead reader."""
    monkeypatch.setattr(runner_mod, "_RUN_LOCK", tmp_path / "run.lock")
    (tmp_path / "run.lock").write_text(
        json.dumps({"engine_pid": None, "owner_pid": 1, "created": time.time()}),
    )
    v = Vault(tmp_path / "v.json")
    v.initialize("pw")
    r = TradeRunner(v)
    monkeypatch.setattr(r, "_write_audit_log", lambda _s: None)
    monkeypatch.setattr(r, "_notify", lambda _s: None)

    blocked = threading.Event()
    reader = threading.Thread(target=blocked.wait, daemon=True)
    reader.start()
    try:
        r._status = RunStatus.RUNNING
        r._proc = _FakeExitedProc(returncode=0)
        r._thread = reader

        r.cancel()
        assert r.snapshot().status == RunStatus.CANCELLED
        assert not r.is_running()
        assert not (tmp_path / "run.lock").exists()  # lock released
    finally:
        blocked.set()


def test_reaper_grace_period_defers_then_recovers(tmp_path, monkeypatch):
    """Within the grace period the reaper must NOT declare a wedge (a
    healthy pump's own finally is about to finalize, and crying 'leaked
    browser' on a clean run would be misleading); once the engine has
    stayed exited-but-RUNNING past the grace it must recover."""
    monkeypatch.setattr(runner_mod, "_RUN_LOCK", tmp_path / "run.lock")
    (tmp_path / "run.lock").write_text(
        json.dumps({"engine_pid": None, "owner_pid": 1, "created": time.time()}),
    )
    v = Vault(tmp_path / "v.json")
    v.initialize("pw")
    r = TradeRunner(v)
    monkeypatch.setattr(r, "_write_audit_log", lambda _s: None)
    monkeypatch.setattr(r, "_notify", lambda _s: None)

    r._status = RunStatus.RUNNING
    r._proc = _FakeExitedProc(returncode=0)
    r._thread = None

    # First observation: engine just seen exited -> defer, still RUNNING,
    # and no misleading recovery message written.
    assert r.is_running() is True
    assert r._engine_exit_seen is not None
    assert "auto-recovering" not in r.log.getvalue()

    # Simulate the grace period elapsing, then it must recover.
    r._engine_exit_seen -= runner_mod._REAP_GRACE_SECONDS + 0.5
    assert r.is_running() is False
    assert r.snapshot().status == RunStatus.FINISHED


def test_finalize_guard_never_clobbers_a_newer_run(tmp_path, monkeypatch):
    """A stale reader/reaper for an OLD proc must not clobber the status
    of a NEWER run that already took over (``_start`` installs a fresh
    proc). ``_finalize``'s proc-identity guard enforces this."""
    monkeypatch.setattr(runner_mod, "_RUN_LOCK", tmp_path / "run.lock")
    v = Vault(tmp_path / "v.json")
    v.initialize("pw")
    r = TradeRunner(v)

    old_proc = _FakeExitedProc(returncode=0)
    new_proc = _FakeExitedProc(returncode=0)
    # Simulate: a newer run is active with new_proc, but a stale path
    # tries to finalize the OLD proc.
    r._status = RunStatus.RUNNING
    r._proc = new_proc
    assert r._finalize(old_proc, RunStatus.FINISHED) is False
    assert r._status == RunStatus.RUNNING  # newer run untouched
    # Finalizing the actual active proc works.
    assert r._finalize(new_proc, RunStatus.FINISHED) is True
    assert r._status == RunStatus.FINISHED


def test_terminal_status_total_failure_is_error(tmp_path):
    """Engine exits 0 even when every broker failed; a run where the
    progress map shows failures and zero successes must be ERROR, not a
    green FINISHED (which would fire a 'run finished' webhook)."""
    v = Vault(tmp_path / "v.json")
    v.initialize("pw")
    r = TradeRunner(v)

    # All brokers failed, engine exited 0 -> ERROR.
    r._progress = {"fidelity": "failed", "chase": "failed"}
    assert r._terminal_status(0, cancelled=False) == RunStatus.ERROR

    # At least one success -> FINISHED (per-broker dots still show fails).
    r._progress = {"fidelity": "failed", "bbae": "done"}
    assert r._terminal_status(0, cancelled=False) == RunStatus.FINISHED

    # done_no_fill counts as a clean run.
    r._progress = {"bbae": "done_no_fill"}
    assert r._terminal_status(0, cancelled=False) == RunStatus.FINISHED

    # No progress emitted (e.g. holdings) -> trust the exit code.
    r._progress = {}
    assert r._terminal_status(0, cancelled=False) == RunStatus.FINISHED

    # Non-zero exit -> ERROR; cancelled flag wins.
    assert r._terminal_status(1, cancelled=False) == RunStatus.ERROR
    assert r._terminal_status(0, cancelled=True) == RunStatus.CANCELLED


def test_runner_single_instance_lock(tmp_path, monkeypatch):
    lock = tmp_path / "run.lock"
    monkeypatch.setattr(runner_mod, "_RUN_LOCK", lock)
    import os

    v = Vault(tmp_path / "v.json")
    v.initialize("pw")

    # A live *engine* pid -> lock is held, not stale.
    monkeypatch.setattr(
        runner_mod.TradeRunner, "_engine_pid_state",
        staticmethod(lambda _pid: "engine"),
    )
    lock.write_text(json.dumps({"engine_pid": os.getpid(), "created": time.time()}))
    with pytest.raises(RunBusyError):
        TradeRunner(v)._acquire_run_lock()

    # A dead pid -> stale -> reclaimable.
    monkeypatch.setattr(
        runner_mod.TradeRunner, "_engine_pid_state",
        staticmethod(lambda _pid: "dead"),
    )
    lock.write_text(json.dumps({"engine_pid": 999999999, "created": time.time()}))
    TradeRunner(v)._acquire_run_lock()
    assert lock.exists()


def test_runner_lock_reclaimed_on_pid_reuse(tmp_path, monkeypatch):
    """A recorded engine pid that is now a live NON-engine process (the OS
    reused the pid after a crash) must be treated as stale, not wedge every
    run forever. But an un-inspectable live pid stays held (never risk a
    concurrent LIVE run)."""
    lock = tmp_path / "run.lock"
    monkeypatch.setattr(runner_mod, "_RUN_LOCK", lock)
    v = Vault(tmp_path / "v.json")
    v.initialize("pw")
    lock.write_text(json.dumps({"engine_pid": 4242, "created": time.time()}))

    # PID reused by an unrelated live process -> reclaimable.
    monkeypatch.setattr(
        runner_mod.TradeRunner, "_engine_pid_state",
        staticmethod(lambda _pid: "other"),
    )
    TradeRunner(v)._acquire_run_lock()
    assert lock.exists()

    # Un-inspectable live pid + fresh lock -> conservatively held.
    lock.write_text(json.dumps({"engine_pid": 4242, "created": time.time()}))
    monkeypatch.setattr(
        runner_mod.TradeRunner, "_engine_pid_state",
        staticmethod(lambda _pid: "unknown"),
    )
    with pytest.raises(RunBusyError):
        TradeRunner(v)._acquire_run_lock()
