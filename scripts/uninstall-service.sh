#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="brados-sec.service"
SERVICE_DST="$HOME/.config/systemd/user/$SERVICE_NAME"

if [ ! -f "$SERVICE_DST" ]; then
    echo "Service not installed at $SERVICE_DST"
    exit 0
fi

systemctl --user stop "$SERVICE_NAME" 2>/dev/null || true
systemctl --user disable "$SERVICE_NAME" 2>/dev/null || true
rm -f "$SERVICE_DST"
systemctl --user daemon-reload

echo "Uninstalled: $SERVICE_NAME"
