#!/bin/bash
# Starts the VTP web interface on Linux or Termux: bash run-web.sh [--port 9000] [--no-browser]
# Serves the page at http://127.0.0.1:8765/ (this device only) and opens it in the default browser.
# Stop it with Ctrl+C. Needs .venv from setup.sh / setup-termux.sh; missing web packages are
# installed here. Don't run it together with run.sh: the Telegram session allows one program at a time.

# Run from the project folder, wherever the script is called from
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

# Virtual environments made before the web interface or video posts lack these packages
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

# -B: don't write __pycache__ folders. Arguments (--port, --no-browser) are passed on.
python3 -B kernel/webapp.py "$@"

if command -v termux-wake-unlock >/dev/null 2>&1; then
    termux-wake-unlock
fi
echo ""
echo "[i] Web server stopped."
