#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

echo "=== Firewall Demo Traffic Generator — Installer ==="
echo ""

# System packages need root
if [[ $EUID -ne 0 ]]; then
    echo "This script needs root to install system packages. Re-running with sudo..."
    exec sudo --preserve-env=HOME "$0" "$@"
fi

echo "[1/4] Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
    python3 \
    python3-pip \
    python3-venv \
    python3-full \
    iputils-ping \
    dnsutils \
    openssh-client \
    > /dev/null

echo "[2/4] Creating Python virtual environment..."
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

echo "[3/4] Installing Python dependencies..."
pip install -q -r "$SCRIPT_DIR/requirements.txt"

echo "[4/4] Installing Playwright Chromium browser (including system deps)..."
python3 -m playwright install --with-deps chromium

REAL_USER="${SUDO_USER:-$(whoami)}"
mkdir -p "$SCRIPT_DIR/logs"
chown -R "$REAL_USER":"$REAL_USER" "$SCRIPT_DIR/logs" "$VENV_DIR"

echo ""
echo "=== Installation complete ==="
echo ""
echo "Run the generator:"
echo "  ./run.sh              # TUI mode"
echo "  ./run.sh --headless   # Console-only mode"
