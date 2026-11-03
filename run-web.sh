#!/bin/bash

# Force the current working directory to match the script's actual location
cd "$(dirname "$0")"

echo "========================================================"
echo "  VTP - WEB INTERFACE LAUNCHER"
echo "========================================================"
echo ""

if [ ! -f ".venv/bin/activate" ]; then
    echo "[!] Virtual environment not found."
    echo "    Run setup.sh (or setup-termux.sh on Android) first."
    exit 1
fi

source .venv/bin/activate

# Older installs don't have the web packages yet
if ! python3 -c "import fastapi, uvicorn" >/dev/null 2>&1; then
    echo "[~] Installing the web interface packages (fastapi, uvicorn)..."
    pip install -r requirements.txt || exit 1
fi

# On Termux, keep Android from suspending the server while the screen is off
if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock
fi

python3 -B kernel/webapp.py "$@"

if command -v termux-wake-unlock >/dev/null 2>&1; then
    termux-wake-unlock
fi
echo ""
echo "[i] Web server stopped."
