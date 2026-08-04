#!/usr/bin/env bash
set -euo pipefail

echo "=== Firewall Demo Traffic Generator — Installer ==="
echo ""

# Require root for apt operations
if [[ $EUID -ne 0 ]]; then
    echo "This script needs root to install system packages. Re-running with sudo..."
    exec sudo "$0" "$@"
fi

echo "[1/4] Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
    python3 \
    python3-pip \
    python3-venv \
    iputils-ping \
    dnsutils \
    openssh-client \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libxshmfence1 \
    > /dev/null

echo "[2/4] Installing Python dependencies..."
pip3 install -q -r requirements.txt

echo "[3/4] Installing Playwright Chromium browser..."
python3 -m playwright install --with-deps chromium

echo "[4/4] Creating logs directory..."
mkdir -p logs

echo ""
echo "=== Installation complete ==="
echo ""
echo "Run the generator:"
echo "  python3 -m demo_generator              # TUI mode"
echo "  python3 -m demo_generator --headless    # Console-only mode"
