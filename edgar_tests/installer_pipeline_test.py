"""Windows installer pipeline: friend-profile patch + frozen engine spawn."""

import importlib.util
import os
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    p = _ROOT / "build" / "windows" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_bw_{name}", p)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_apply_friend_profile_sets_both_flags(tmp_path):
    apply_mod = _load("apply_friend_profile")
    dst = tmp_path / "_keys.py"
    dst.write_text(
        (_ROOT / "src" / "license" / "_keys.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    apply_mod.apply(dst)
    text = dst.read_text(encoding="utf-8")
    assert "SIMPLE_MODE_DEFAULT: bool = True" in text
    assert "REQUIRE_LICENSE_TO_TRADE: bool = True" in text


def test_apply_friend_profile_missing_flag_raises(tmp_path):
    apply_mod = _load("apply_friend_profile")
    dst = tmp_path / "_keys.py"
    dst.write_text("X = 1\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        apply_mod.apply(dst)


def test_engine_command_source_path(monkeypatch):
    from src.gui.core import runner

    monkeypatch.delenv("AUTORSA_FROZEN", raising=False)
    cmd = runner._engine_command("PAYLOAD")
    assert cmd[1:] == ["-u", "-m", "src.gui.core.engine_proc", "PAYLOAD"]


def test_engine_command_frozen_path(monkeypatch):
    from src.gui.core import runner

    monkeypatch.setenv("AUTORSA_FROZEN", "1")
    cmd = runner._engine_command("PAYLOAD")
    assert cmd[1:] == ["--engine", "PAYLOAD"]


def test_launcher_resolves_app_script_and_config(monkeypatch):
    launcher = _load("launcher")
    assert launcher.app_script().endswith("app.py")
    monkeypatch.delenv("STREAMLIT_SERVER_HEADLESS", raising=False)
    launcher._configure_streamlit()
    assert os.environ["STREAMLIT_SERVER_HEADLESS"] == "true"
