import os
import random
import asyncio
import re
import sys

# Tell Python NOT to write .pyc files or __pycache__ folders
sys.dont_write_bytecode = True

# Import existing auth manager (assumed to be in the same directory)
import auth_manager
from common import load_channels_config, get_latest_session_directory

def parse_target(target):
    """
    Smart Parser: Safely converts string-based numerical IDs into true Integers for Telethon,
    while leaving standard @usernames and 'me' untouched.
    """
    if not target:
        return None
    if isinstance(target, str):
        target = target.strip()
        # If it's all digits (or a negative sign followed by digits), cast to int
        if target.lstrip('-').isdigit():
            return int(target)
    return target

def build_caption(md_path, profile):
    """Stitches the channel's header, the bold headline, the body and the footer into caption HTML."""
    with open(md_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    headline = lines[0].lstrip("#").strip() if lines else ""
    body = "".join(lines[1:]).strip()

    # Parse headers/footers and fix JSON escaped newlines
    captions_cfg = profile.get("caption_settings", {})
    header = captions_cfg.get("header_template", "").replace("\\n", "\n").strip()
    footer = captions_cfg.get("footer_template", "").replace("\\n", "\n").strip()

    # The header and the headline share the first line
    head_block = ""
    if header:
        head_block += header
    if headline:
        if head_block:
            head_block += " " # Add a single space separation if header exists
        head_block += f"<b>{headline}</b>"

    # Compile final layout blocks
    final_text = []
    if head_block: final_text.append(head_block)
    if body: final_text.append(body)
    if footer: final_text.append(footer)

    compiled_caption = "\n\n".join(final_text)

    # Whitespace inside <tg-emoji> tags shifts Telethon's entity offsets
    compiled_caption = re.sub(r'(<tg-emoji[^>]*>)\s+', r'\1', compiled_caption)
    compiled_caption = re.sub(r'\s+(</tg-emoji>)', r'\1', compiled_caption)
    return compiled_caption

def generate_all_caption_files(session_dir, config):
    """
    Stitches header, headline, body, and footer for EVERY channel defined in config.
    Saves them to editable .txt files in the session subdirectory.
    """
    print("\n[~] Pre-generating editable caption files for ALL channels...")
    channels = config.get("channels", {})

    for channel_internal_name, profile in channels.items():
        lang = profile.get("language", "en")

        md_path = os.path.join(session_dir, f"{lang}.md")
        txt_path = os.path.join(session_dir, f"{channel_internal_name}_caption.txt")

        # Skip if the user has already generated/edited the file (preserving manual edits)
        if os.path.exists(txt_path):
            continue

        if not os.path.exists(md_path):
            print(f"  [!] Missing source markdown for {channel_internal_name} ({lang}.md). Caption not generated.")
            continue

        compiled_caption = build_caption(md_path, profile)

        # Save to session directory
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(compiled_caption)
        print(f"  [+] Created: {channel_internal_name}_caption.txt")

def select_channels_ui(channels_dict):
    """Provides a Terminal UI for selecting channels."""
    print("\n========================================================")
    print("  TELEGRAM PUBLISHER: TARGET SELECTION")
    print("========================================================")

    channel_keys = sorted(channels_dict.keys())

    for i, ch_name in enumerate(channel_keys, 1):
        print(f"  [{i}] {ch_name} (Lang: {channels_dict[ch_name].get('language')})")
    print("  [A] All Channels")
    print("========================================================")
    print("Instructions: Enter indices separated by commas (e.g., 1,3,4) or 'A'.")

    choice = input("[?] Select channels: ").strip().lower()

    if choice == 'a':
        return channel_keys

    try:
        indices = [int(idx.strip()) - 1 for idx in choice.split(',') if idx.strip().isdigit()]
        return [channel_keys[idx] for idx in indices if 0 <= idx < len(channel_keys)]
    except (ValueError, IndexError):
        print("[ERROR] Invalid selection input format.")
        return []

async def compile_and_send_post(client, target_peer, session_dir, channel_internal_name, log_prefix=""):
    """Reloads the LATEST image and text from disk and sends them via Telethon.

    Returns the sent message, or None if a file is missing or sending failed.
    """
    img_path = os.path.join(session_dir, f"{channel_internal_name}_broadcast.jpg")
    txt_path = os.path.join(session_dir, f"{channel_internal_name}_caption.txt")

    if not os.path.exists(img_path):
        print(f"{log_prefix} [X] Skipping {channel_internal_name}: Image file not found at {img_path}")
        return None
    if not os.path.exists(txt_path):
        print(f"{log_prefix} [X] Skipping {channel_internal_name}: Caption file not found at {txt_path}")
        return None

    with open(txt_path, "r", encoding="utf-8") as f:
        caption_text = f.read()

    try:
        return await client.send_file(
            target_peer,
            file=img_path,
            caption=caption_text,
            parse_mode="html"
        )
    except Exception as e:
        print(f"{log_prefix} [ERROR] Failed to send post for {channel_internal_name}: {e}")
        return None

async def warm_up_entity_cache(client):
    """Loads recent dialogs so Telethon can resolve numeric IDs of private groups and channels."""
    print("\n[~] Warming up Telethon entity cache (syncing with Telegram)...")
    try:
        await client.get_dialogs(limit=50)
        print("  [+] Cache synced.")
    except Exception:
        print("  [!] Cache sync skipped (Non-fatal).")

async def send_previews(client, catch_all_gate, session_dir, channel_names):
    """Sends each channel's post to the review channel. Returns {channel: sent message or None}."""
    print(f"\n[~] Dispatching previews to Catch-All Gate ({catch_all_gate})...")
    sent = {}
    for ch_name in channel_names:
        print(f"  -> Sending preview for {ch_name}...")
        sent[ch_name] = await compile_and_send_post(client, catch_all_gate, session_dir, ch_name)
        await asyncio.sleep(random.uniform(3.0, 8.0))
    return sent

async def publish_live(client, channels_dict, session_dir, channel_names):
    """Posts each channel's post to its live chat_id. Returns {channel: sent message or None}."""
    print("\n========================================================")
    print("  INITIATING LIVE BROADCAST")
    print("========================================================")

    sent = {}
    for ch_name in channel_names:
        # Safely parse the Live Chat ID
        raw_chat_id = channels_dict[ch_name].get("chat_id")
        live_chat_id = parse_target(raw_chat_id)

        if not live_chat_id:
            print(f"  [X] Skipping {ch_name}: No chat_id defined in config.")
            sent[ch_name] = None
            continue

        print(f"  -> Final re-creation and publishing to {ch_name} ({live_chat_id})...")
        sent[ch_name] = await compile_and_send_post(client, live_chat_id, session_dir, ch_name, log_prefix="  ->")

        if sent[ch_name]:
            print(f"  [+] Successfully published to {ch_name}.")

        await asyncio.sleep(random.uniform(5.0, 10.0))

    print("\n[SUCCESS] Live broadcast complete.")
    return sent

async def main(session_dir=None):
    """Publishes the given session, or the latest one when run on its own."""
    session_dir = session_dir or get_latest_session_directory()
    if not session_dir:
        print("[ERROR] No session directory found inside _workspace.")
        return

    print(f"\n[OK] Onboarded to session: _workspace/{os.path.basename(session_dir)}/")

    config = load_channels_config()

    generate_all_caption_files(session_dir, config)

    channels_dict = config.get("channels", {})
    selected_ch_names = select_channels_ui(channels_dict)

    if not selected_ch_names:
        print("[!] No channels selected. Exiting pipeline.")
        return

    print(f"\n[+] Pipeline locked for {len(selected_ch_names)} target(s).")

    print("\n[~] Authenticating user session via auth_manager...")
    client = auth_manager.get_client()

    if not client:
        print("[ERROR] Could not initialize client via auth_manager.")
        return

    # Safely parse the Catch-All Gate ID
    catch_all_gate = parse_target(config.get("catch_all_channel"))
    final_approval_granted = False

    async with client:
        await warm_up_entity_cache(client)

        while True:
            if catch_all_gate:
                await send_previews(client, catch_all_gate, session_dir, selected_ch_names)

            print("\n========================================================")
            print("  REVIEW & APPROVAL")
            print("  [A] Approve (Re-creates and publishes to live channels)")
            print("  [R] Retry (Preserves edits, resends to Catch-All Gate)")
            print("  [S] Stall (Pause pipeline and exit without live broadcast)")
            print("========================================================")

            action = input("\n[?] Select action: ").strip().lower()

            if action == 's':
                print("[!] Pipeline stalled. Exiting. Live broadcast aborted.")
                final_approval_granted = False
                break

            elif action == 'r':
                print("[+] Reloading assets from disk and repeating review loop...")
                continue

            elif action == 'a':
                print("[OK] Final approval granted! Preparing live broadcast.")
                final_approval_granted = True
                break
            else:
                print("[!] Invalid option. Please enter A, R, or S.")

        if final_approval_granted:
            await publish_live(client, channels_dict, session_dir, selected_ch_names)

    print("\nPublishing pipeline complete.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] Publisher terminated by user.")
