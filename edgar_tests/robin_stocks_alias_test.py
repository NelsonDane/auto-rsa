"""Guard the vendored robin_stocks aliasing in auto_rsa.py (finding INST-1).

The vendored library self-references its OWN top-level name: its __init__ does
``from robin_stocks import gemini, robinhood, tda`` and submodules do
``from robin_stocks.tda.helper import ...``. So ``sys.modules["robin_stocks"]``
must be registered BEFORE the package body executes. A naive
``import src.vendors...robin_stocks; sys.modules.setdefault("robin_stocks", …)``
sets the alias AFTER the body has already run its self-reference — which then
raises ``ModuleNotFoundError``, gets swallowed, and leaves the alias unset,
taking Robinhood (and, via the shared broker-import block, the whole engine)
down at import on every run.

These tests pin the WORKING technique (register-before-exec) with a tiny
self-referential fixture package — which is deterministic and needs none of
the engine's heavy deps — and guard auto_rsa.py against reverting to the
after-exec ordering.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _make_self_referential_pkg(root: Path, top: str, holder: str) -> None:
    """Create ``<root>/<holder>/<top>/`` whose __init__ self-references ``top``.

    Mirrors the robin_stocks shape: an inner package that lives at a nested
    dotted path (``<holder>.<top>``) but whose own code imports it as the
    bare top-level name ``<top>``.
    """
    (root / holder).mkdir(parents=True)
    (root / holder / "__init__.py").write_text("", encoding="utf-8")
    pkg = root / holder / top
    pkg.mkdir()
    pkg.joinpath("__init__.py").write_text(f"from {top} import sub\n", encoding="utf-8")
    pkg.joinpath("sub.py").write_text("VALUE = 42\n", encoding="utf-8")


def _forget(*names: str) -> None:
    for n in names:
        sys.modules.pop(n, None)


def test_naive_import_of_self_referential_pkg_fails(tmp_path, monkeypatch):
    # Reproduces the bug: importing the inner package by its REAL dotted name
    # runs the self-reference before any top-level alias exists.
    _make_self_referential_pkg(tmp_path, top="rsnaive", holder="holdn")
    monkeypatch.syspath_prepend(str(tmp_path))
    _forget("holdn", "holdn.rsnaive", "rsnaive", "rsnaive.sub")
    try:
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("holdn.rsnaive")
    finally:
        _forget("holdn", "holdn.rsnaive", "rsnaive", "rsnaive.sub")


def test_register_before_exec_resolves_self_reference(tmp_path, monkeypatch):
    # The fix: find_spec + module_from_spec + register the top-level alias
    # BEFORE exec_module, so the package's self-reference resolves. This is the
    # exact technique auto_rsa.py uses for robin_stocks — and it is
    # filesystem-independent (works for a compiled/frozen module too).
    _make_self_referential_pkg(tmp_path, top="rsgood", holder="holdg")
    monkeypatch.syspath_prepend(str(tmp_path))
    _forget("holdg", "holdg.rsgood", "rsgood", "rsgood.sub")
    inner = "holdg.rsgood"
    try:
        spec = importlib.util.find_spec(inner)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules["rsgood"] = mod  # <-- alias registered BEFORE exec
        sys.modules[inner] = mod
        spec.loader.exec_module(mod)  # `from rsgood import sub` now resolves
        assert mod.sub.VALUE == 42
        # Same object under both names (what unifies robinhood_api's import).
        assert sys.modules["rsgood"] is sys.modules[inner]
    finally:
        _forget("holdg", "holdg.rsgood", "rsgood", "rsgood.sub")


def test_auto_rsa_registers_alias_before_exec():
    # Guard against reverting to the buggy "alias AFTER a plain import" order.
    src = (_ROOT / "src" / "auto_rsa.py").read_text(encoding="utf-8")
    assert 'sys.modules["robin_stocks"] = ' in src
    # Anchor on the actual CALL token (".exec_module(") — a bare "exec_module"
    # also appears in the explanatory comment, which precedes the code.
    assert ".exec_module(" in src
    # The alias must be set BEFORE the body is executed.
    assert src.index('sys.modules["robin_stocks"] = ') < src.index(".exec_module(")
    # The specific broken pattern must not come back.
    assert 'setdefault("robin_stocks"' not in src
    assert (
        "import src.vendors.robin_stocks.robin_stocks as _robin_stocks" not in src
    )
