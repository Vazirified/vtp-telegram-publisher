import sys
# Force Python to stop generating __pycache__ folders completely
sys.dont_write_bytecode = True

import os
import asyncio

# --- FIX PATH TRAP ---
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from kernel.auth_manager import get_client

# Correct Telethon modules for exporting formatted text
from telethon.extensions.markdown import unparse as markdown_unparse
from telethon.extensions.html import unparse as html_unparse

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

        entity_name = getattr(channel, 'title', None) or getattr(channel, 'first_name', 'Saved Messages')
        print(f"[~] Fetching recent messages from {entity_name}...\n")

        async for message in client.iter_messages(channel, limit=10):
            if message.text:
                preview = message.text[:40].replace('\n', ' ')
                print(f"==================================================")
                print(f"[Message ID: {message.id}] Preview: {preview}...")

                # 1. Properly translate internal message entities back to formatting tags
                if message.entities:
                    print(f"  --> Ready Markdown text string:")
                    try:
                        md_text = markdown_unparse(message.message, message.entities)
                        print(f"      {md_text}")
                    except Exception as e:
                        print(f"      [Could not unparse Markdown: {e}]")

                    print(f"  --> Ready HTML text string:")
                    try:
                        html_text = html_unparse(message.message, message.entities)
                        print(f"      {html_text}")
                    except Exception as e:
                        print(f"      [Could not unparse HTML: {e}]")
                else:
                    print(f"  --> Plain Text (No inner entities): {message.message}")

                # 2. Extract custom emoji document IDs from reactions
                if message.reactions:
                    print("  --> Reactions found:")
                    for r in message.reactions.results:
                        if hasattr(r.reaction, 'emoticon') and r.reaction.emoticon:
                            print(f"      Standard Emoji: {r.reaction.emoticon} (Count: {r.count})")
                        elif hasattr(r.reaction, 'document_id') and r.reaction.document_id:
                            doc_id = r.reaction.document_id
                            print(f"      Custom/Animated Emoji ID: {doc_id} (Count: {r.count})")
                            print(f"      Copy-Paste Markdown tag: ![🌐](tg://emoji?id={doc_id})")
                            print(f"      Copy-Paste HTML tag:     <tg-emoji emoji-id=\"{doc_id}\">🌐</tg-emoji>")
                else:
                    print("  --> No reactions found.")
                print(f"==================================================\n")

    except Exception as e:
        print(f"[ERROR] Could not inspect channel: {e}")
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
