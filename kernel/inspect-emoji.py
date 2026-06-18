import asyncio
from kernel.auth_manager import get_client

async def main():
    # 1. Use the shared auth manager to get the client
    # This will return a TelegramClient configured to look in _credentials/
    client = get_client()

    if not client:
        print("[!] Cannot proceed without valid credentials.")
        return

    print("[~] Connecting to Telegram...")

    # 2. Start the client
    # If 'user_session.session' does not exist in _credentials/,
    # Telethon will trigger an interactive CLI login process here.
    await client.start()

    print("[+] Successfully authenticated.")
    print("--- Emoji Inspection Mode ---")
    target = input("Enter channel/group username (e.g., 'durov'): ").strip()

    try:
        channel = await client.get_entity(target)
        print(f"[~] Fetching recent messages from {channel.title}...")

        async for message in client.iter_messages(channel, limit=10):
            if message.text:
                # Preview text
                preview = message.text[:40].replace('\n', ' ')
                print(f"\n[ID: {message.id}] {preview}...")

                # Reaction Inspection Logic
                if message.reactions:
                    for r in message.reactions.results:
                        emoji = r.reaction.emoticon if hasattr(r.reaction, 'emoticon') else "Custom"
                        print(f"  -> {emoji} ({r.count})")
                else:
                    print("  -> No reactions found.")

    except Exception as e:
        print(f"[ERROR] Could not inspect channel: {e}")
    finally:
        # Close the connection cleanly
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
