#!/usr/bin/env bash
# ====================================================================
#  AutoRSA GUI launcher (macOS). Double-click this file in Finder to
#  start (Finder runs .command files in Terminal). Equivalent of
#  start-gui.cmd on Windows.
#
#  First run only: if macOS says it "cannot verify the developer",
#  right-click -> Open -> Open. (Cloned via git, so normally no prompt.)
# ====================================================================
set -e

# Resolve and enter the repo dir even when double-clicked from anywhere.
cd "$(dirname "${BASH_SOURCE[0]}")"

# uv installs to ~/.local/bin (and Homebrew to /opt/homebrew/bin);
# a double-clicked Terminal may not have these on PATH yet.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"

pause_and_exit() {
  echo
  read -r -p "Press Return to close this window..." _
  exit "${1:-0}"
}

if ! command -v uv >/dev/null 2>&1; then
  echo
  echo "uv is not installed or not on your PATH."
  echo "Install it:  curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo "Then double-click this file again."
  pause_and_exit 1
fi

echo "Syncing dependencies (quick if nothing changed)..."
uv sync || echo "WARNING: dependency sync failed; continuing with the existing environment..."

# Skip Streamlit's first-run interactive "Email:" prompt — on a fresh
# machine it blocks forever waiting on input, so the GUI never starts.
mkdir -p "$HOME/.streamlit"
if [ ! -f "$HOME/.streamlit/credentials.toml" ]; then
  printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"
fi

PORT=8501
URL="http://localhost:${PORT}"

echo
echo "Starting AutoRSA GUI..."
echo "If your browser does not open, go to:  ${URL}"
echo "Keep this window open while using the app. Press Ctrl+C to stop."
echo

# Belt-and-suspenders: open the browser ourselves a few seconds in,
# in case Streamlit's own auto-open is blocked.
( sleep 6; command -v open >/dev/null 2>&1 && open "${URL}" ) &

# --no-sync: don't rebuild the env at launch (sync already ran above).
uv run --no-sync streamlit run src/gui/app.py \
  --server.port="${PORT}" \
  --server.headless=false \
  --browser.gatherUsageStats=false || true

pause_and_exit 0
