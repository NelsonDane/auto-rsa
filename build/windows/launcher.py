"""Packaged launcher for the AutoRSA GUI (Windows one-click build).

The entry point for the Nuitka-compiled standalone build: it runs with NO
uv and NO system Python. It configures Streamlit for local, headless use,
starts the server on localhost, and opens the default browser.

You can (and should) validate this launcher FROM SOURCE before ever
touching Nuitka — it proves the config + Streamlit-start logic works
independently of the freeze:

    python build/windows/launcher.py     # opens http://127.0.0.1:8501
"""

from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

HOST = "127.0.0.1"
PORT = int(os.environ.get("AUTORSA_PORT", "8501"))
URL = f"http://{HOST}:{PORT}"


def _configure_streamlit() -> None:
    """Local-only, headless, no telemetry, no first-run email prompt.

    Set via env vars so it holds regardless of any config.toml on disk.
    ``setdefault`` so an operator override still wins.
    """
    env = os.environ.setdefault
    env("STREAMLIT_SERVER_ADDRESS", HOST)
    env("STREAMLIT_SERVER_PORT", str(PORT))
    env("STREAMLIT_SERVER_HEADLESS", "true")  # also suppresses the email prompt
    env("STREAMLIT_SERVER_ENABLE_CORS", "false")
    env("STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION", "false")
    env("STREAMLIT_SERVER_FILE_WATCHER_TYPE", "none")
    env("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    env("STREAMLIT_GLOBAL_DEVELOPMENT_MODE", "false")


def _base_dir() -> Path:
    # In a Nuitka standalone build the executable dir holds the shipped
    # data files; in dev we're at build/windows/launcher.py.
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        return Path(sys.argv[0]).resolve().parent
    return Path(__file__).resolve().parent


def app_script() -> str:
    """Path to app.py — shipped as a DATA file next to the compiled binary.

    Streamlit runs the app by executing this script, so it must exist on
    disk (the build ships src/gui/app.py verbatim; the imported src.*
    modules are compiled into the binary). See BUILD.md.
    """
    base = _base_dir()
    candidates = (
        base / "src" / "gui" / "app.py",           # packaged (data files)
        base / "app.py",                            # packaged (flat)
        Path(__file__).resolve().parents[2] / "src" / "gui" / "app.py",  # dev
    )
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    raise SystemExit(
        "Could not locate app.py in the build — the Nuitka data-file "
        "include is likely missing. See build/windows/BUILD.md.",
    )


def _is_compiled() -> bool:
    """True when running as the Nuitka-compiled exe (not from source)."""
    return "__compiled__" in globals() or bool(getattr(sys, "frozen", False))


def _run_engine(payload_json: str) -> None:
    """Run the engine — the app exe re-invoked as ``--engine <payload>``.

    In the compiled build the runner can't do ``python -m …``, so it
    re-invokes this exe; engine_proc.main() reads the payload from
    ``sys.argv[1]``, so line it up there and hand off.
    """
    sys.argv = [sys.argv[0], payload_json]
    from src.gui.core import engine_proc  # noqa: PLC0415

    engine_proc.main()


def _open_browser_when_up() -> None:
    import urllib.error  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    deadline = 60  # ~30s
    for _ in range(deadline):
        try:
            urllib.request.urlopen(URL, timeout=1)  # noqa: S310
            break
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    webbrowser.open(URL)


def main() -> None:
    argv = sys.argv[1:]
    # The runner re-invokes this exe as the engine subprocess in a frozen
    # build. Handle that FIRST, before any GUI/Streamlit setup.
    if argv and argv[0] == "--engine":
        _run_engine(argv[1] if len(argv) > 1 else "[]")
        return
    # Tell the runner it's inside the compiled build so it spawns the
    # engine as `AutoRSA.exe --engine …` rather than `python -m …`.
    if _is_compiled():
        os.environ.setdefault("AUTORSA_FROZEN", "1")
    _configure_streamlit()
    app = app_script()
    threading.Thread(target=_open_browser_when_up, daemon=True).start()
    from streamlit.web import bootstrap  # noqa: PLC0415

    # Streamlit 1.57: run(main_script_path, is_hello, args, flag_options).
    bootstrap.run(app, False, [], {})


if __name__ == "__main__":
    main()
