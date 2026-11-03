#!/bin/bash

# Prevent Windows line-ending issues if edited on PC
set -e

# Force the current working directory to match the script's actual location
cd "$(dirname "$0")"

echo "========================================================"
echo "  ePLANET PUBLISHER - LINUX SETUP"
echo "========================================================"
echo ""

# FriBiDi is loaded at runtime by Pillow's Raqm text layout, which shapes the
# Kurdish/Persian/Arabic headlines. Without it, Kurdish letters lose their marks.
has_fribidi() {
    ldconfig -p 2>/dev/null | grep -q "libfribidi\.so" && return 0
    ls /usr/lib/libfribidi.so* /usr/lib64/libfribidi.so* /usr/lib/*/libfribidi.so* >/dev/null 2>&1
}

install_fribidi() {
    local SUDO=""
    if [ "$(id -u)" -ne 0 ]; then
        if command -v sudo >/dev/null 2>&1; then
            SUDO="sudo"
        else
            echo "  [!] Not running as root and sudo is unavailable."
            return 1
        fi
    fi

    if command -v apt-get >/dev/null 2>&1; then
        $SUDO apt-get update && $SUDO apt-get install -y libfribidi0
    elif command -v dnf >/dev/null 2>&1; then
        $SUDO dnf install -y fribidi
    elif command -v yum >/dev/null 2>&1; then
        $SUDO yum install -y fribidi
    elif command -v pacman >/dev/null 2>&1; then
        $SUDO pacman -S --needed --noconfirm fribidi
    elif command -v zypper >/dev/null 2>&1; then
        $SUDO zypper --non-interactive install libfribidi0
    elif command -v apk >/dev/null 2>&1; then
        $SUDO apk add fribidi
    else
        echo "  [!] No supported package manager found (apt, dnf, yum, pacman, zypper, apk)."
        return 1
    fi
}

# Step 1: Make sure the FriBiDi system library is present
echo "[~] Checking for the FriBiDi text library..."
if has_fribidi; then
    echo "  [OK] FriBiDi is already installed."
else
    echo "  [~] FriBiDi not found. Installing it with the system package manager..."
    install_fribidi || echo "  [!] Automatic FriBiDi installation failed. Install it manually (e.g. 'sudo apt install libfribidi0')."
fi

# Step 2: Build the virtual environment
echo "[~] Creating isolated Python virtual environment..."
PYTHON_BIN=$(command -v python3 || command -v python)
"$PYTHON_BIN" -m venv .venv

# Step 3: Activate the environment safely
echo "[~] Activating virtual environment..."
source .venv/bin/activate

# Step 4: Upgrade pip inside the sandbox
echo "[~] Upgrading pip to the latest version..."
pip install --upgrade pip

# Step 5: Install the Python dependencies
echo "[~] Installing required pipeline engines..."
pip install -r requirements.txt

# Step 6: Confirm Pillow can actually use Raqm (i.e. it found FriBiDi)
echo "[~] Verifying Raqm text layout for Kurdish/Persian/Arabic headlines..."
if python -c "from PIL import features; import sys; sys.exit(0 if features.check('raqm') else 1)"; then
    echo "  [OK] Raqm is active (FriBiDi $(python -c "from PIL import features; print(features.version('fribidi'))"))."
    RAQM_STATUS="[OK] Raqm text layout is active."
else
    echo "  [!] WARNING: Raqm is NOT active. Kurdish headlines will render with misspelled letters."
    echo "      Install FriBiDi (e.g. 'sudo apt install libfribidi0') and run this setup again."
    RAQM_STATUS="[!] Raqm text layout is NOT active (see warning above)."
fi

echo ""
echo "========================================================"
echo "  [OK] Linux environment setup is complete!"
echo "  $RAQM_STATUS"
echo "  [->] You can now launch the pipeline using: bash ./run.sh"
echo "========================================================"
