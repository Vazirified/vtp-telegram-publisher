import os
import json
from telethon import TelegramClient

# Determine the absolute project root (one level above the 'kernel' folder)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREDENTIALS_DIR = os.path.join(PROJECT_ROOT, "_credentials")
CREDENTIALS_FILE = os.path.join(CREDENTIALS_DIR, "telegram_api.json")
# Telethon will append '.session' to this path automatically
SESSION_FILE = os.path.join(CREDENTIALS_DIR, "user_session")

def get_client():
    """
    Initializes and returns an authenticated TelegramClient.
    Ensures the _credentials directory exists before attempting to load or create files.
    """
    # Ensure the _credentials directory exists
    if not os.path.exists(CREDENTIALS_DIR):
        try:
            os.makedirs(CREDENTIALS_DIR, exist_ok=True)
            print(f"[+] Created missing directory: {CREDENTIALS_DIR}")
        except Exception as e:
            print(f"[ERROR] Could not create credentials directory: {e}")
            return None

    # Check if credentials file exists
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"[ERROR] API credentials not found at: {CREDENTIALS_FILE}")
        print("[!] Please create this file with 'api_id' and 'api_hash' keys.")
        return None

    try:
        with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        api_id = data.get("api_id")
        api_hash = data.get("api_hash")

        if not api_id or not api_hash:
            print("[ERROR] 'api_id' or 'api_hash' missing from JSON file.")
            return None

        # Initialize client
        client = TelegramClient(SESSION_FILE, api_id, api_hash)
        return client

    except json.JSONDecodeError:
        print("[ERROR] Failed to parse JSON in telegram_api.json.")
        return None
    except Exception as e:
        print(f"[ERROR] An unexpected error occurred during initialization: {e}")
        return None
