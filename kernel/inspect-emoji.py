import os
import sys
import asyncio

# --- FIX PATH TRAP ---
# Dynamically add the project root directory to Python's search path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Now Python can see the 'kernel' package perfectly
from kernel.auth_manager import get_client

async def main():
    client = get_client()
    if not client:
        return

    print("[~] Connecting to Telegram...")
    await client.start()

    print("[+] Successfully authenticated.")
    print("--- Emoji Inspection Mode ---")
    target = input("Enter channel/group username (e.g., 'durov'): ").strip()

    try:
        channel = await client.get_entity(target)
        print(f"[~] Fetching recent messages from {channel.title}...")

        async for message in client.iter_messages(channel, limit=10):
            if message.text:
                preview = message.text[:40].replace('\n', ' ')
                print(f"\n[ID: {message.id}] {preview}...")

                if message.reactions:
                    for r in message.reactions.results:
                        emoji = r.reaction.emoticon if hasattr(r.reaction, 'emoticon') else "Custom"
                        print(f"  -> {emoji} ({r.count})")
                else:
                    print("  -> No reactions found.")

    except Exception as e:
        print(f"[ERROR] Could not inspect channel: {e}")
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
