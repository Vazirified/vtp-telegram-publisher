#!/bin/bash
# Starts the VTP terminal + window interface (kernel/main.py) on Linux or Termux (under Termux:X11):
# bash run.sh
# Offers to run setup.sh when .venv is missing. After each post it asks whether to run again
# (yes after 5 seconds). Answering N at the first question opens a shell inside the virtual
# environment instead, e.g. to run kernel/publisher.py or kernel/configurator.py by hand.
# Don't run it together with run-web.sh: the Telegram session allows one program at a time.

# Run from the project folder, wherever the script is called from
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

# Step 2: Activate the virtual environment
echo "[->] Initializing isolated environment runtime..."
source .venv/bin/activate
echo "[OK] Environment sandbox is live."
echo ""

# Step 3: Ask whether to start main.py; no answer within 5 seconds means yes
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
    # Run main.py (one post per run) until the user answers N to the relaunch question
    while true; do
        echo ""
        echo "--------------------------------------------------------"
        echo "[->] Launching master pipeline..."
        echo "--------------------------------------------------------"
        # -B: don't write __pycache__ folders (main.py also turns this off itself)
        python3 -B kernel/main.py
        echo "--------------------------------------------------------"
        echo "[i] Script execution complete."
        echo "--------------------------------------------------------"
        
        # Prompt for relaunch
        read -t 5 -n 1 -p "[?] Run orchestrator again? [Y/n] (Auto-relaunching in 5s): " relaunch_choice
        echo ""
        
        if [ -z "$relaunch_choice" ]; then
            relaunch_choice="Y"
        fi
        
        if [[ "$relaunch_choice" =~ ^[Nn]$ ]]; then
            echo ""
            echo "[i] Exiting launcher..."
            break
        fi
    done
fi