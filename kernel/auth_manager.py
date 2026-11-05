"""Creates the Telethon client every VTP tool uses to reach Telegram.

Reads _credentials/telegram_api.json ({"api_id": ..., "api_hash": ...}, from my.telegram.org)
and keeps the login in _credentials/user_session.session. That session file can be open in only
one program at a time: run the web interface or the terminal tools (main.py, publisher.py,
inspect-emoji.py), not both. Used by the terminal tools and by telegram_service (web interface).
"""
import os
import json
from telethon import TelegramClient

from common import CREDENTIALS_DIR

CREDENTIALS_FILE = os.path.join(CREDENTIALS_DIR, "telegram_api.json")
# Telethon will append '.session' to this path automatically
SESSION_FILE = os.path.join(CREDENTIALS_DIR, "user_session")

def get_client():
    """Returns a TelegramClient for the saved API ID and hash, or None (with an [ERROR] line) if they're missing.

    The client is not connected yet. Callers connect it; when the session isn't logged in, the
    terminal tools let Telethon ask for phone and code, and the web interface logs in on its Setup page.
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

        client = TelegramClient(SESSION_FILE, api_id, api_hash)
        return client

    except json.JSONDecodeError:
        print("[ERROR] Failed to parse JSON in telegram_api.json.")
        return None
    except Exception as e:
        print(f"[ERROR] An unexpected error occurred during initialization: {e}")
        return None
