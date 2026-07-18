#!/data/data/com.termux/files/usr/bin/bash
# BradOS bootstrap for Termux.
#
# Usage (from the repo root, inside Termux):
#   bash scripts/termux-setup.sh
#
set -euo pipefail

echo "== BradOS Termux setup =="

echo "-- Updating package index --"
pkg update -y

echo "-- Installing Python + prebuilt psutil/cryptography where available --"
# These are the packages most likely to need a compile from source if pip
# builds them itself, so we prefer Termux's own prebuilt binaries first.
pkg install -y python python-cryptography python-psutil git || true

# Fallback toolchain in case this Termux mirror doesn't carry prebuilt
# python-cryptography / python-psutil — lets `pip install` compile them.
if ! python3 -c "import cryptography" 2>/dev/null; then
    echo "-- python-cryptography prebuilt not available; installing build toolchain --"
    pkg install -y clang rust openssl binutils
fi

echo "-- Installing remaining Python dependencies --"
pip install --upgrade pip
pip install -e . --no-deps
pip install -r requirements-termux.txt

echo
echo "== Setup complete =="
echo "Run BradOS with:      python brados.py"
echo "Run the desktop shell directly with:   python brados.py --shell"
echo
echo "Notes for Termux:"
echo "  - The Docker-backed mail server is unavailable (no Docker on Termux)."
echo "    'bpkg' and the rest of BradOS work normally; that one feature will"
echo "    report Docker as not found and no-op, same as on any machine"
echo "    without Docker installed."
echo "  - brados-sec.service (systemd) does not apply here — Termux has no"
echo "    systemd. The security daemon still runs in-process automatically"
echo "    when you launch BradOS; for start-on-boot behavior instead, install"
echo "    the Termux:Boot app and add a boot script that runs"
echo "    'python brados.py --daemon' (see TERMUX.md)."
echo "  - Keep Termux in the foreground (or hold a wakelock via"
echo "    'termux-wake-lock') if you want background daemons/mesh networking"
echo "    to keep running — Android aggressively suspends background apps."
