#!/bin/bash
set -euo pipefail

TMPDIR=/tmp/xvfb
mkdir -p "$TMPDIR"
rm -f "$TMPDIR/.X99-lock"

echo "Starting X virtual framebuffer (Xvfb) in background..."
Xvfb -ac :99 -screen 0 1280x1024x16 -nolisten tcp -nolisten unix -fbdir "$TMPDIR" &
export DISPLAY=:99

echo "Starting Auto RSA Bot..."
# exec python autoRSA.py docker
exec auto_rsa_bot docker
