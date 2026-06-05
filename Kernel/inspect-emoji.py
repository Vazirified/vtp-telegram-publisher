import os
import json
from telethon import TelegramClient, events

# Compute absolute paths relative to project root with lowercase structure
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
CREDENTIALS_DIR = os.path.join(PROJECT_ROOT, "_credentials")
KEYS_FILE = os.path.join(CREDENTIALS_DIR, "telegram_keys.json")
SESSION_FILE = os.path.join(CREDENTIALS_DIR, "inspector_session")

def get_telegram_app_credentials():
    """
    Ensures _credentials exists, reads app keys if available,
    or interviews the user once to save them state-lessly.
    """
    if not os.path.exists(CREDENTIALS_DIR):
        os.makedirs(CREDENTIALS_DIR)

    if os.path.exists(KEYS_FILE):
        try:
            with open(KEYS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return int(data["api_id"]), data["api_hash"]
        except (json.JSONDecodeError, KeyError, ValueError, IOError):
            print("[!] Credentials configuration corrupted. Re-initializing.")

    print("+------------------------------------------------------+")
    print(":     TELEGRAM APPLICATION DEVELOPER REGISTRATION     :")
    print("+------------------------------------------------------+")
    print("[i] To connect to Telegram, you need your App API keys.")
    print("[i] Get them instantly by logging into: https://my.telegram.org")
    print("--------------------------------------------------------")

    try:
        api_id = int(input("[?] Enter your numeric API ID: ").strip())
        api_hash = input("[?] Enter your alphanumeric API Hash: ").strip()
    except ValueError:
        print("[ERROR] API ID must be a number. Execution terminated.")
        exit(1)

    with open(KEYS_FILE, "w", encoding="utf-8") as f:
        json.dump({"api_id": api_id, "api_hash": api_hash}, f, indent=2)

    print("[OK] Application credentials committed to _credentials/telegram_keys.json")
    return api_id, api_hash

def main():
    api_id, api_hash = get_telegram_app_credentials()

    print("\n[-->] Initializing user authorization handshake...")
    client = TelegramClient(SESSION_FILE, api_id, api_hash)

    @client.on(events.NewMessage(outgoing=True))
    async def handler(event):
        if event.entities:
            for entity in event.entities:
                if hasattr(entity, 'document_id'):
                    print("\n========================================================")
                    print(f"  [FOUND] Custom Emoji Target Match: {event.raw_text}")
                    print(f"  [FOUND] Token Value: [eid:{entity.document_id}]")
                    print("========================================================\n")

    print("\n========================================================")
    print("  EMOJI INSPECTOR MONITOR RUNNING ACTIVE")
    print("========================================================")
    print("  [Instructions]")
    print("  1. Open your standard Telegram Mobile or Desktop app.")
    print("  2. Send any Premium Animated Emoji into your Saved Messages.")
    print("  3. The parsed token will print below instantly.")
    print("  4. Press Ctrl+C inside this terminal window to stop.")
    print("========================================================\n")

    try:
        client.start()
        client.run_until_disconnected()
    except KeyboardInterrupt:
        print("\n[-->] Intercept listener killed. Returning to system shell.")

if __name__ == "__main__":
    main()
