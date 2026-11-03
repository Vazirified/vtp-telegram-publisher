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

# 2b. Text shaping libraries for Pillow's Raqm layout (Kurdish/Persian/Arabic headlines)
echo "[~] Installing FriBiDi and HarfBuzz text shaping libraries..."
pkg install fribidi harfbuzz -y
pkg install libraqm -y || echo "  [i] libraqm package not available; Pillow's bundled Raqm will be used instead."

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
pip install -r requirements.txt

# 9. Confirm Pillow can use Raqm; if not, rebuild Pillow with its bundled Raqm
raqm_active() {
    python -c "from PIL import features; import sys; sys.exit(0 if features.check('raqm') else 1)"
}

echo "[~] Verifying Raqm text layout for Kurdish/Persian/Arabic headlines..."
if ! raqm_active; then
    echo "  [~] Raqm not active. Rebuilding Pillow from source with bundled Raqm (this takes a few minutes)..."
    pip install --force-reinstall --no-cache-dir --no-binary pillow pillow -C raqm=vendor -C fribidi=vendor \
        || echo "  [!] Pillow rebuild failed."
fi

if raqm_active; then
    echo "  [OK] Raqm is active (FriBiDi $(python -c "from PIL import features; print(features.version('fribidi'))"))."
    RAQM_STATUS="[OK] Raqm text layout is active."
else
    echo "  [!] WARNING: Raqm is NOT active. Kurdish headlines will render with misspelled letters."
    echo "      Check that 'pkg install fribidi harfbuzz' succeeded, then run this setup again."
    RAQM_STATUS="[!] Raqm text layout is NOT active (see warning above)."
fi

echo ""
echo "========================================================"
echo " [SUCCESS] System initialization complete!"
echo " $RAQM_STATUS"
echo " Web interface (no X11 needed): bash run-web.sh"
echo " Terminal + window interface: boot Termux:X11 app and run: bash run.sh"
echo "========================================================"
