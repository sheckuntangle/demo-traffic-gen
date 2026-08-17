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

REAL_USER="${SUDO_USER:-$(whoami)}"
MIN_PYTHON=(3 8)

echo "[1/6] Installing system packages..."
apt-get update -qq

# Check if system python3 meets the minimum version
NEED_DEADSNAKES=false
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 -c 'import sys; print(sys.version_info.major, sys.version_info.minor)')
    PY_MAJ=${PY_VER%% *}; PY_MIN=${PY_VER##* }
    if (( PY_MAJ < MIN_PYTHON[0] || (PY_MAJ == MIN_PYTHON[0] && PY_MIN < MIN_PYTHON[1]) )); then
        NEED_DEADSNAKES=true
    fi
else
    NEED_DEADSNAKES=true
fi

if $NEED_DEADSNAKES; then
    echo "  System Python is too old (need >= ${MIN_PYTHON[0]}.${MIN_PYTHON[1]}). Installing Python 3.10 from deadsnakes PPA..."
    apt-get install -y -qq software-properties-common > /dev/null
    add-apt-repository -y ppa:deadsnakes/ppa > /dev/null 2>&1
    apt-get update -qq
    apt-get install -y -qq python3.10 python3.10-venv python3.10-distutils > /dev/null
    PYTHON=python3.10
else
    PYTHON=python3
fi

PKG_LIST=(iputils-ping dnsutils openssh-client curl)
if apt-cache show python3-full &>/dev/null; then
    PKG_LIST+=(python3-full)
fi
apt-get install -y -qq "${PKG_LIST[@]}" > /dev/null
echo "  Using $($PYTHON --version)"

echo "[2/6] Installing Docker..."
if command -v docker &> /dev/null; then
    echo "  Docker already installed: $(docker --version)"
else
    curl -fsSL https://get.docker.com | sh
    echo "  Docker installed: $(docker --version)"
fi
if ! groups "$REAL_USER" | grep -q docker; then
    usermod -aG docker "$REAL_USER"
    echo "  Added $REAL_USER to docker group (re-login required for docker commands)"
fi
systemctl enable docker
systemctl start docker

echo "[3/6] Creating Python virtual environment..."
$PYTHON -m venv "$VENV_DIR"

echo "[4/6] Installing Python dependencies..."
"$VENV_DIR/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt"

echo "[5/6] Installing Playwright Chromium browser (including system deps)..."
"$VENV_DIR/bin/python3" -m playwright install --with-deps chromium

echo "[6/6] Setting up sudoers for IP aliasing..."
mkdir -p "$SCRIPT_DIR/logs"
chown -R "$REAL_USER":"$REAL_USER" "$SCRIPT_DIR/logs" "$VENV_DIR"

SUDOERS_FILE="/etc/sudoers.d/demo-traffic-gen"
cat > "$SUDOERS_FILE" <<SUDOERS
# Allow the traffic generator web GUI to manage IP aliases
$REAL_USER ALL=(root) NOPASSWD: /sbin/ip addr add *
$REAL_USER ALL=(root) NOPASSWD: /sbin/ip addr del *
$REAL_USER ALL=(root) NOPASSWD: /usr/sbin/ip addr add *
$REAL_USER ALL=(root) NOPASSWD: /usr/sbin/ip addr del *
SUDOERS
chmod 440 "$SUDOERS_FILE"

echo ""
echo "=== Installation complete ==="
echo ""
echo "Run the generator:"
echo "  ./run.sh              # Web GUI at http://localhost:8080"
echo "  ./run.sh --headless   # Console-only mode"
echo ""
echo "Docker client mode:"
echo "  Configure macvlan clients in the web GUI Configuration tab"
echo "  Requires re-login if you were just added to the docker group"
