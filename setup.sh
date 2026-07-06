#!/bin/bash

# Prevent Windows line-ending issues if edited on PC
set -e

echo "========================================================"
echo "  ePLANET PUBLISHER - LINUX/TERMUX SETUP"
echo "========================================================"
echo ""

# Step 1: Build the virtual environment
echo "[~] Creating isolated Python virtual environment..."
python -m venv .venv

# Step 2: Activate the environment safely
echo "[~] Activating virtual environment..."
source .venv/bin/activate

# Step 3: Upgrade pip inside the sandbox
echo "[~] Upgrading pip to the latest version..."
pip install --upgrade pip

# Step 4: Inline Dependency Installation (No requirements.txt needed!)
echo "[~] Installing required pipeline engines..."
pip install telethon pillow arabic-reshaper python-bidi google-genai

echo ""
echo "========================================================"
echo "  [OK] Linux environment setup is complete!"
echo "  [->] You can now launch the pipeline using: bash ./run.sh"
echo "========================================================"