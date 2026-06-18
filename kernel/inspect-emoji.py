import os
import json
from telethon import TelegramClient

# --- PATH CONFIGURATION ---
# Assumes this script is in a subdirectory.
# If this script is in the root, change to: PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

CREDENTIALS_FILE = os.path.join(PROJECT_ROOT, "_credentials", "telegram_api.json")
SESSION_FILE = os.path.join(PROJECT_ROOT, "_credentials", "user_session")

def get_credentials():
    """Loads API credentials from the central _credentials/ directory."""
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"[ERROR] Configuration file missing at: {CREDENTIALS_FILE}")
        exit(1)

    with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        return data.get("api_id"), data.get("api_hash")

async def main():
    api_id, api_hash = get_credentials()

    # Initialize client using the session path inside _credentials/
    client = TelegramClient(SESSION_FILE, api_id, api_hash)

    print("[~] Connecting to Telegram...")
    await client.start()

    print("[+] Successfully authenticated.")
    print("--- Emoji Inspection Mode ---")
    print("Enter the name of a public channel/group (e.g., 'durov') to inspect its recent posts.")

    target = input("Channel/Group: ").strip()

    try:
        channel = await client.get_entity(target)
        async for message in client.iter_messages(channel, limit=10):
            if message.text:
                print(f"\n[ID: {message.id}] {message.text[:50]}...")
                # Inspecting reactions/emojis
                if message.reactions:
                    for reaction in message.reactions.results:
                        # Extracting emoji or custom reaction
                        if reaction.reaction.emoticon:
                            print(f"  -> Found Emoji: {reaction.reaction.emoticon} | Count: {reaction.count}")
                        elif reaction.reaction.document_id:
                            print(f"  -> Found Custom Emoji (DocID: {reaction.reaction.document_id}) | Count: {reaction.count}")
                else:
                    print("  -> No reactions found.")

    except Exception as e:
        print(f"[ERROR] Could not inspect channel: {e}")
    finally:
        await client.disconnect()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
