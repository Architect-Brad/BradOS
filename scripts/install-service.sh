#!/usr/bin/env bash
set -euo pipefail

BRADOS_HOME="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="$(command -v python3 || command -v python)"
SERVICE_NAME="brados-sec.service"
SERVICE_SRC="$BRADOS_HOME/$SERVICE_NAME"
SERVICE_DST="$HOME/.config/systemd/user/$SERVICE_NAME"

if [ ! -f "$SERVICE_SRC" ]; then
    echo "Error: $SERVICE_SRC not found. Run from the BradOS repo root."
    exit 1
fi

if [ -z "$PYTHON_BIN" ]; then
    echo "Error: python3 not found in PATH."
    exit 1
fi

mkdir -p "$HOME/.config/systemd/user"

sed -e "s|BRADOS_HOME|$BRADOS_HOME|g" \
    -e "s|PYTHON_BIN|$PYTHON_BIN|g" \
    "$SERVICE_SRC" > "$SERVICE_DST"

echo "Installed: $SERVICE_DST"
echo "  Python:   $PYTHON_BIN"
echo "  Work dir: $BRADOS_HOME"

systemctl --user daemon-reload
systemctl --user enable "$SERVICE_NAME"
systemctl --user start "$SERVICE_NAME"

echo ""
echo "Status:"
systemctl --user --no-pager status "$SERVICE_NAME" 2>&1 | head -12
