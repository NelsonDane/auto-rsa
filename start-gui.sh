#!/usr/bin/env bash
# ====================================================================
#  AutoRSA GUI launcher (macOS / Linux).
#  Run with:  ./start-gui.sh   (or double-click if your file manager
#  is set to run shell scripts).
# ====================================================================
set -e
cd "$(dirname "$0")"

# Make sure uv is reachable even from a minimal environment.
export PATH="$PATH:$HOME/.local/bin"

# Repo root on PYTHONPATH so the app's `from src import ...` resolves
# (the bare `streamlit` script only adds src/gui/ to sys.path).
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

if ! command -v uv >/dev/null 2>&1; then
  echo
  echo "uv is not installed or not on your PATH."
  echo "Install it from https://docs.astral.sh/uv/ then run this again."
  echo
  exit 1
fi

echo "Syncing dependencies (quick if nothing changed)..."
uv sync || echo "WARNING: dependency sync failed; continuing with the existing environment..."

# Browser binary for Fidelity automation (patchright bundles its own;
# not installed by uv sync). Idempotent; ~150MB only on a fresh box.
echo "Ensuring the automation browsers are installed..."
uv run --no-sync patchright install chromium \
  || echo "WARNING: chromium install failed; run 'uv run --no-sync patchright install chromium' manually."
# Schwab (schwab_api) uses Playwright Firefox, separate from the above.
uv run --no-sync playwright install firefox \
  || echo "WARNING: firefox install failed; run 'uv run --no-sync playwright install firefox' manually."

# Chase (zendriver) and Wells Fargo / Vanguard (Selenium) drive the
# SYSTEM Chrome. Warn if it's missing (don't auto-install an app).
if ! { [ -d "/Applications/Google Chrome.app" ] || [ -d "/Applications/Chromium.app" ] \
       || command -v google-chrome >/dev/null 2>&1 \
       || command -v chromium >/dev/null 2>&1 \
       || command -v chromium-browser >/dev/null 2>&1; }; then
  echo "WARNING: system Google Chrome not found — Chase / Wells Fargo /"
  echo "         Vanguard need it. macOS: brew install --cask google-chrome"
fi

# Skip Streamlit's first-run interactive "Email:" prompt — on a fresh
# machine it blocks forever waiting on input, so the GUI never starts.
mkdir -p "$HOME/.streamlit"
if [ ! -f "$HOME/.streamlit/credentials.toml" ]; then
  printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"
fi

echo
echo "Starting AutoRSA GUI - your browser will open automatically."
echo "If it does not, open:  http://localhost:8501"
echo "Keep this terminal open while using the app. Ctrl+C to stop."
echo
exec uv run --no-sync python -m streamlit run src/gui/app.py \
  --server.port=8501 --server.headless=false \
  --browser.gatherUsageStats=false
