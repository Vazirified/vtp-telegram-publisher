#!/bin/bash
# Stop immediately if any command fails
set -e

echo "========================================================"
echo "      AUTOMATED ENGINE INITIALIZER FOR ANDROID"
echo "========================================================"

# 1. Update Termux Packages safely
echo "[~] Refreshing repository links..."
pkg update -y && pkg upgrade -y

# 2. Install native system tools and compiler frameworks
echo "[~] Injecting compiler libraries (Rust/Clang)..."
pkg install rust binutils clang python-tkinter python-cryptography xorg-xkbcomp xkeyboard-config -y

# 3. Patch the known Termux X11 repository keymap path bug
echo "[~] Executing X11 structural environment repair..."
rm -rf $PREFIX/share/X11/xkb
ln -sf $PREFIX/share/xkeyboard-config-2 $PREFIX/share/X11/xkb

# 4. Permanently configure the local X11 display environment variable
if ! grep -q "export DISPLAY=:0" ~/.bashrc; then
    echo "export DISPLAY=:0" >> ~/.bashrc
    echo "[~] Display path successfully appended to user profile."
fi
export DISPLAY=:0

# 5. Build isolated Python ecosystem with host inheritance
echo "[~] Formatting project directories and virtual environments..."
cd ~/vtp---vazirified-telegram-publisher
rm -rf .venv
python -m venv --system-site-packages .venv

# 6. Activate sandboxed environment and clear out conflicting PyPI files
source .venv/bin/activate
pip install --upgrade pip

# 7. Dynamically map host cryptography libraries directly to sandbox
PYTHON_VER=$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
cd .venv/lib/python$PYTHON_VER/site-packages/
ln -sf $PREFIX/lib/python$PYTHON_VER/site-packages/cryptography .
ln -sf $PREFIX/lib/python$PYTHON_VER/site-packages/cryptography-*.dist-info .
cd ~/vtp---vazirified-telegram-publisher

# 8. Pull remaining lightweight components
echo "[~] Syncing pipeline modules (Telethon/Pillow/Bidi)..."
pip install telethon pillow arabic-reshaper python-bidi google-genai

echo ""
echo "========================================================"
echo " [SUCCESS] System initialization complete!"
echo " Boot Termux:X11 app and run: bash run.sh"
echo "========================================================"
