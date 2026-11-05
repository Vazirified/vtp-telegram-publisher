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
if ! python3 -c "import fastapi, uvicorn, imageio_ffmpeg" >/dev/null 2>&1; then
    echo "[~] Installing the web interface packages (fastapi, uvicorn, imageio-ffmpeg)..."
    pip install -r requirements.txt || exit 1
fi

# Video posts need ffmpeg; on Termux it comes from pkg (imageio-ffmpeg has no Android build)
if command -v pkg >/dev/null 2>&1 && ! command -v ffmpeg >/dev/null 2>&1; then
    echo "[~] Installing ffmpeg for video posts..."
    pkg install ffmpeg -y || echo "[!] ffmpeg couldn't be installed; video posts won't work."
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
