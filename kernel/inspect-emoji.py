import os
import sys
import asyncio

# --- FIX PATH TRAP ---
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from kernel.auth_manager import get_client

async def main():
    client = get_client()
    if not client:
        return

    print("[~] Connecting to Telegram...")
    await client.start()

    print("[+] Successfully authenticated.")
    print("--- Emoji Inspection Mode ---")
    target = input("Enter channel/group username (or 'me' for Saved Messages): ").strip()

    try:
        channel = await client.get_entity(target)

        # Safely resolve name whether it's a Channel (title) or a User (first_name)
        entity_name = getattr(channel, 'title', None) or getattr(channel, 'first_name', 'Saved Messages')
        print(f"[~] Fetching recent messages from {entity_name}...")

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
