#!/bin/bash
# VTP setup for Android (Termux). Run once: bash setup-termux.sh
# The project folder must be ~/vtp---vazirified-telegram-publisher (the paths below assume it).
# - Installs Termux packages: compilers for Python packages without Android wheels, Tkinter and
#   X11 keyboard data (for the terminal + window interface under Termux:X11), FriBiDi/HarfBuzz
#   (headline shaping) and ffmpeg (video posts).
# - Recreates .venv (any existing one is deleted) with access to Termux's own Python packages,
#   then installs requirements.txt.
# - Makes sure Pillow's Raqm text layout works, rebuilding Pillow from source if needed.
# Afterwards: bash run-web.sh (web interface, opens in the phone's browser), or start the
# Termux:X11 app and run bash run.sh (terminal + window interface).

# Stop immediately if any command fails
set -e

echo "========================================================"
echo "      AUTOMATED ENGINE INITIALIZER FOR ANDROID"
echo "========================================================"

# 1. Update Termux Packages safely
echo "[~] Refreshing repository links..."
pkg update -y && pkg upgrade -y

# 2. Compilers (some Python packages are built from source on Android), Tkinter, the prebuilt
#    cryptography package, and X11 keyboard data for Termux:X11
echo "[~] Injecting compiler libraries (Rust/Clang)..."
pkg install rust binutils clang python-tkinter python-cryptography xorg-xkbcomp xkeyboard-config -y

# 2b. Text shaping libraries for Pillow's Raqm layout (Kurdish/Persian/Arabic headlines)
echo "[~] Installing FriBiDi and HarfBuzz text shaping libraries..."
pkg install fribidi harfbuzz -y
pkg install libraqm -y || echo "  [i] libraqm package not available; Pillow's bundled Raqm will be used instead."

# 2c. ffmpeg for video posts in the web interface (imageio-ffmpeg has no Android build and uses this one)
echo "[~] Installing ffmpeg for video posts..."
pkg install ffmpeg -y

# 3. Termux's X11 looks for keyboard maps in share/X11/xkb, but xkeyboard-config installs them
#    in share/xkeyboard-config-2: point the first at the second
echo "[~] Executing X11 structural environment repair..."
rm -rf $PREFIX/share/X11/xkb
ln -sf $PREFIX/share/xkeyboard-config-2 $PREFIX/share/X11/xkb

# 4. Point windows at the Termux:X11 display, now and in every new shell (~/.bashrc)
if ! grep -q "export DISPLAY=:0" ~/.bashrc; then
    echo "export DISPLAY=:0" >> ~/.bashrc
    echo "[~] Display path successfully appended to user profile."
fi
export DISPLAY=:0

# 5. Recreate the virtual environment; --system-site-packages lets it use Termux's
#    python-tkinter and python-cryptography instead of building them
echo "[~] Formatting project directories and virtual environments..."
cd ~/vtp---vazirified-telegram-publisher
rm -rf .venv
python -m venv --system-site-packages .venv

# 6. Activate the virtual environment and upgrade pip
source .venv/bin/activate
pip install --upgrade pip

# 7. Link Termux's cryptography package into the virtual environment, so pip sees it as
#    installed and doesn't try to build it from source (that needs Rust and often fails)
PYTHON_VER=$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
cd .venv/lib/python$PYTHON_VER/site-packages/
ln -sf $PREFIX/lib/python$PYTHON_VER/site-packages/cryptography .
ln -sf $PREFIX/lib/python$PYTHON_VER/site-packages/cryptography-*.dist-info .
cd ~/vtp---vazirified-telegram-publisher

# 8. Install the Python packages listed in requirements.txt. imageio-ffmpeg has no Android
#    binary and uses the ffmpeg installed in step 2c.
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
