#!/bin/bash

# Force the current working directory to match the script's actual location
cd "$(dirname "$0")"

echo "========================================================"
echo "  ePLANET PUBLISHER - SERVICE LAUNCHER (LINUX)"
echo "========================================================"
echo ""

# Step 1: Check if the virtual environment exists
if [ ! -f ".venv/bin/activate" ]; then
    echo "[!] System environment is not initialized."
    echo ""
    read -p "[?] Virtual environment not found. Run setup.sh now? [y/N]: " setup_choice
    
    if [[ "$setup_choice" =~ ^[Yy]$ ]]; then
        echo "--------------------------------------------------------"
        echo "[->] Handing over execution control to setup.sh..."
        echo "--------------------------------------------------------"
        bash setup.sh
        exit 0
    else
        echo "--------------------------------------------------------"
        echo "[i] Exiting launcher. Please run ./setup.sh manually."
        echo "--------------------------------------------------------"
        exit 1
    fi
fi

# Step 2: Safe activation of the virtual environment container
echo "[->] Initializing isolated environment runtime..."
source .venv/bin/activate
echo "[OK] Environment sandbox is live."
echo ""

# Step 3: Interactive Prompt Routing with 5-Second Auto-Timeout
# -t 5 sets the timer. -n 1 captures a single keystroke.
read -t 5 -n 1 -p "[?] Launch master orchestrator? [Y/n] (Auto-launching in 5s): " exec_choice
echo ""

# If the user presses nothing (timeout or just Enter), default to Y
if [ -z "$exec_choice" ]; then
    exec_choice="Y"
fi

if [[ "$exec_choice" =~ ^[Nn]$ ]]; then
    echo ""
    echo "--------------------------------------------------------"
    echo "[i] Bypassing script execution."
    echo "    Entering manual command line override mode."
    echo "    Type 'exit' to leave this shell."
    echo "--------------------------------------------------------"
    echo ""
    # Drop the user into a bash shell with the venv still active
    exec bash
else
    echo ""
    echo "--------------------------------------------------------"
    echo "[->] Launching master pipeline..."
    echo "--------------------------------------------------------"
    # Added the -B flag as a secondary safeguard against __pycache__ folders
    python3 -B kernel/main.py
    echo "--------------------------------------------------------"
    echo "[i] Script execution complete."
    read -p "Press [Enter] to exit..."
fi