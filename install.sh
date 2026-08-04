#!/usr/bin/env bash
set -euo pipefail

echo "=== Firewall Demo Traffic Generator — Installer ==="
echo ""

# Require root for apt operations
if [[ $EUID -ne 0 ]]; then
    echo "This script needs root to install system packages. Re-running with sudo..."
    exec sudo "$0" "$@"
fi

echo "[1/3] Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
    python3 \
    python3-pip \
    python3-venv \
    iputils-ping \
    dnsutils \
    openssh-client \
    > /dev/null

echo "[2/3] Installing Python dependencies..."
pip3 install -q -r requirements.txt

echo "[3/3] Installing Playwright Chromium browser (including system deps)..."
python3 -m playwright install --with-deps chromium

echo "Creating logs directory..."
mkdir -p logs

echo ""
echo "=== Installation complete ==="
echo ""
echo "Run the generator:"
echo "  python3 -m demo_generator              # TUI mode"
echo "  python3 -m demo_generator --headless    # Console-only mode"
