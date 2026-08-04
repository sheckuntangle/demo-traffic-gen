#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

if [[ ! -d "$VENV_DIR" ]]; then
    echo "Virtual environment not found. Run ./install.sh first."
    exit 1
fi

cd "$SCRIPT_DIR"
exec "$VENV_DIR/bin/python3" -m demo_generator "$@"
