#!/bin/bash

# Force the current working directory to match the script's actual location
cd "$(dirname "$0")"

echo "========================================================"
echo "  ePLANET PUBLISHER - LINUX SETUP"
echo "========================================================"
echo ""

# Check if python3 is installed
if ! command -v python3 &> /dev/null; then
    echo "[!] Python 3 could not be found."
    echo "    Please install it using: sudo apt install python3 python3-venv python3-tk"
    exit 1
fi

echo "[~] Creating isolated Python virtual environment..."
python3 -m venv .venv

echo "[~] Activating virtual environment..."
source .venv/bin/activate

echo "[~] Upgrading pip to the latest version..."
pip install --upgrade pip

echo "[~] Installing pipeline dependencies from requirements.txt..."
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
else
    echo "[!] WARNING: requirements.txt not found in the root directory!"
fi

echo ""
echo "========================================================"
echo "  [OK] Linux environment setup is complete!"
echo "  [->] You can now launch the pipeline using ./run.sh"
echo "========================================================"