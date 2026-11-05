"""Publishing phase: builds each channel's caption and sends its image (or video) to Telegram.

Flow: captions are made from <lang>.md into <channel>_caption.txt (existing files are kept, so
hand edits survive), the user picks channels, previews go to the review channel
(catch_all_channel), and after approval each channel's post goes to its chat_id. Files are
read from disk at every send, so captions and images can be fixed between previews.

- Terminal interface: main.py calls main(session_dir) at the end of a run. Run on its own, it
  publishes the LATEST session folder in _workspace/:
      python kernel/publisher.py
- Web interface: pipeline_service/webapp use the non-interactive parts: build_caption,
  parse_target, send_previews and publish_live (with on_sent for progress).

Session files read: <channel>_broadcast.jpg (or, for a video post, <channel>_broadcast.mp4 with
the .jpg as thumbnail and video_info.json for its duration), <channel>_caption.txt, <lang>.md.

Settings read from _config/channels.json: catch_all_channel, and per channel: chat_id,
language, caption_settings.header_template and caption_settings.footer_template.
"""
import io
import os
import random
import asyncio
import re
import sys

# No .pyc files or __pycache__ folders in the project
sys.dont_write_bytecode = True

# Telethon client with the saved login (_credentials/)
import auth_manager
# Imported before PIL so the bundled FriBiDi is on PATH
from common import load_channels_config, get_latest_session_directory, find_raw_video, load_video_info
from PIL import Image
from telethon.tl.types import DocumentAttributeVideo

# Telegram shows a video's thumbnail only if it is a JPEG of at most 320 px per side
THUMBNAIL_SIZE = 320

def parse_target(target):
    """Turns a chat_id / catch_all_channel value into what Telethon expects.

    Numeric IDs written as strings ("-100...") become ints; @usernames and 'me' (Saved Messages)
    stay strings. Empty values give None.
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
    """Stitches the channel's header, the bold headline, the body and the footer into caption HTML.

    Layout: "<header> <b>headline</b>", blank line, body, blank line, footer. The templates are
    Telegram HTML (custom emoji as <tg-emoji> tags) and may contain a literal \\n for a line break.
    """
    with open(md_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    headline = lines[0].lstrip("#").strip() if lines else ""
    body = "".join(lines[1:]).strip()

    # A "\n" typed in the configurator is stored as backslash + n; turn it into a real line break
    captions_cfg = profile.get("caption_settings", {})
    header = captions_cfg.get("header_template", "").replace("\\n", "\n").strip()
    footer = captions_cfg.get("footer_template", "").replace("\\n", "\n").strip()

    # The header and the headline share the first line
    head_block = ""
    if header:
        head_block += header
    if headline:
        if head_block:
            head_block += " "
        head_block += f"<b>{headline}</b>"

    # Blocks separated by a blank line; empty ones are left out
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
    """Terminal interface: writes <channel>_caption.txt with build_caption() for every channel.

    A caption file that already exists is left alone, so edits made to it are kept. Delete it
    to have it made again from <lang>.md.
    """
    print("\n[~] Pre-generating editable caption files for ALL channels...")
    channels = config.get("channels", {})

    for channel_internal_name, profile in channels.items():
        lang = profile.get("language", "en")

        md_path = os.path.join(session_dir, f"{lang}.md")
        txt_path = os.path.join(session_dir, f"{channel_internal_name}_caption.txt")

        if os.path.exists(txt_path):
            continue

        if not os.path.exists(md_path):
            print(f"  [!] Missing source markdown for {channel_internal_name} ({lang}.md). Caption not generated.")
            continue

        compiled_caption = build_caption(md_path, profile)

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(compiled_caption)
        print(f"  [+] Created: {channel_internal_name}_caption.txt")

def select_channels_ui(channels_dict):
    """Terminal interface: lists the channels (alphabetically) and returns the chosen names.

    Accepts numbers separated by commas, or A for all; anything else selects nothing.
    """
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

def video_thumbnail(still_path):
    """The channel's still (its rendered image) as the video's thumbnail: an in-memory JPEG of at
    most THUMBNAIL_SIZE px; Telethon takes the file name from .name."""
    with Image.open(still_path) as img:
        thumb = img.convert("RGB")
    thumb.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE))
    data = io.BytesIO()
    thumb.save(data, "JPEG", quality=85)
    data.name = "thumbnail.jpg"
    data.seek(0)
    return data

def video_send_options(session_dir, still_path):
    """send_file() options that make Telegram show the video inline and stream it.

    Telethon can only read a video's duration and size with the optional hachoir package, so
    they are given here: the duration from video_info.json, the size from the still (the
    video is the same size, rounded down to even numbers for H.264). nosound_video keeps a
    silent (or muted) video a video; otherwise Telegram may show it as a looping GIF.
    """
    with Image.open(still_path) as img:
        width, height = img.size
    duration = load_video_info(session_dir).get("duration") or 0
    return {
        "supports_streaming": True,
        "nosound_video": True,
        "thumb": video_thumbnail(still_path),
        "attributes": [DocumentAttributeVideo(duration=duration, w=width - width % 2, h=height - height % 2,
                                               supports_streaming=True)],
    }

async def compile_and_send_post(client, target_peer, session_dir, channel_internal_name, log_prefix=""):
    """Sends one channel's post: its image (a video post: video) with the caption as HTML.

    Both are read from disk now, so the latest edits are sent. A post is a video post when the
    session folder has a raw_video.* file. Returns the sent message, or None if a file is missing
    or sending failed (the error is printed, not raised).
    """
    img_path = os.path.join(session_dir, f"{channel_internal_name}_broadcast.jpg")
    txt_path = os.path.join(session_dir, f"{channel_internal_name}_caption.txt")
    is_video = bool(find_raw_video(session_dir))
    media_path = os.path.join(session_dir, f"{channel_internal_name}_broadcast.mp4") if is_video else img_path

    if not os.path.exists(media_path):
        print(f"{log_prefix} [X] Skipping {channel_internal_name}: {'Video' if is_video else 'Image'} file not found at {media_path}")
        return None
    if not os.path.exists(txt_path):
        print(f"{log_prefix} [X] Skipping {channel_internal_name}: Caption file not found at {txt_path}")
        return None

    with open(txt_path, "r", encoding="utf-8") as f:
        caption_text = f.read()

    try:
        options = video_send_options(session_dir, img_path) if is_video else {}
        return await client.send_file(
            target_peer,
            file=media_path,
            caption=caption_text,
            parse_mode="html",
            **options
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

async def send_previews(client, catch_all_gate, session_dir, channel_names, on_sent=None):
    """Sends each channel's post to the review channel. Returns {channel: sent message or None}.

    on_sent(channel, message or None) is called after each channel, e.g. to show progress.
    Sends are 3-8 s apart (random), to stay within Telegram's flood limits.
    """
    print(f"\n[~] Dispatching previews to Catch-All Gate ({catch_all_gate})...")
    sent = {}
    for ch_name in channel_names:
        print(f"  -> Sending preview for {ch_name}...")
        sent[ch_name] = await compile_and_send_post(client, catch_all_gate, session_dir, ch_name)
        if on_sent:
            on_sent(ch_name, sent[ch_name])
        await asyncio.sleep(random.uniform(3.0, 8.0))
    return sent

async def publish_live(client, channels_dict, session_dir, channel_names, on_sent=None):
    """Posts each channel's post to its live chat_id. Returns {channel: sent message or None}.

    on_sent(channel, message or None) is called after each channel, e.g. to show progress.
    A channel without chat_id is skipped (None). Sends are 5-10 s apart (random), for Telegram's
    flood limits.
    """
    print("\n========================================================")
    print("  INITIATING LIVE BROADCAST")
    print("========================================================")

    sent = {}
    for ch_name in channel_names:
        raw_chat_id = channels_dict[ch_name].get("chat_id")
        live_chat_id = parse_target(raw_chat_id)

        if not live_chat_id:
            print(f"  [X] Skipping {ch_name}: No chat_id defined in config.")
            sent[ch_name] = None
            if on_sent:
                on_sent(ch_name, None)
            continue

        print(f"  -> Final re-creation and publishing to {ch_name} ({live_chat_id})...")
        sent[ch_name] = await compile_and_send_post(client, live_chat_id, session_dir, ch_name, log_prefix="  ->")

        if sent[ch_name]:
            print(f"  [+] Successfully published to {ch_name}.")
        if on_sent:
            on_sent(ch_name, sent[ch_name])

        await asyncio.sleep(random.uniform(5.0, 10.0))

    print("\n[SUCCESS] Live broadcast complete.")
    return sent

async def main(session_dir=None):
    """Terminal interface: publishes the given session, or the latest one when run on its own.

    Makes missing captions, asks for the channels, then loops: previews to catch_all_channel
    (skipped when it's empty), and [A]pprove (publish live), [R]etry (send the previews again,
    e.g. after editing a caption file) or [S]tall (exit without publishing).
    """
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

    # The review channel; previews are skipped when it isn't set
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
