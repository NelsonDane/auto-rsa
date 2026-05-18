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

if ! command -v uv >/dev/null 2>&1; then
  echo
  echo "uv is not installed or not on your PATH."
  echo "Install it from https://docs.astral.sh/uv/ then run this again."
  echo
  exit 1
fi

echo "Syncing dependencies (quick if nothing changed)..."
uv sync || echo "WARNING: dependency sync failed; continuing with the existing environment..."

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
exec uv run --no-sync streamlit run src/gui/app.py \
  --server.port=8501 --server.headless=false \
  --browser.gatherUsageStats=false
