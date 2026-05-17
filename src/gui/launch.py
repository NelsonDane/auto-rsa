"""Console entry point that boots the Streamlit GUI.

Usage:
    uv run auto_rsa_gui
or:
    uv run streamlit run src/gui/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    """Launch the Streamlit app in the browser."""
    from streamlit.web import cli as stcli  # noqa: PLC0415

    app_path = str(Path(__file__).resolve().parent / "app.py")
    sys.argv = ["streamlit", "run", app_path]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
