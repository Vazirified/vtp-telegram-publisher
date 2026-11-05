"""Paths and helpers shared by every VTP module (terminal tools and web interface alike).

Folders, all next to the 'kernel' folder and kept out of git:
  _config/channels.json        the channels: Telegram targets, templates, fonts, caption HTML
  _credentials/                telegram_api.json (API ID and hash), user_session.session
                               (Telethon login; one program at a time can use it) and
                               gemini_keys.json (Gemini API key and last used model)
  _workspace/session_<timestamp>_<slug>/   one folder per post

A post's session folder holds:
  <lang>.md                    "# Headline", a blank line, then the body (one file per language)
  raw_image.<ext>              the photo of a photo post
  raw_video.<ext>, video_info.json, video_frame.png, video_preview.mp4   a video post (see below)
  <channel>_broadcast.jpg      the channel's rendered image (for a video post: the still / thumbnail)
  <channel>_broadcast.mp4      the channel's rendered video (video posts only)
  <channel>_caption.txt        the channel's caption (Telegram HTML)
  web_render.json, web_publish_log.json   web interface state (area, blur, overrides; what was sent)

Import this module before PIL in any module that draws text (see the PATH setup below).
"""
import os
import sys
import glob
import json
import time

# Absolute path layout (project root is one level above the 'kernel' folder)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(PROJECT_ROOT, "_config", "channels.json")
WORKSPACE_DIR = os.path.join(PROJECT_ROOT, "_workspace")
CREDENTIALS_DIR = os.path.join(PROJECT_ROOT, "_credentials")
GEMINI_KEYS_FILE = os.path.join(CREDENTIALS_DIR, "gemini_keys.json")

# Fallback model, used only when no model was saved yet and the live model list can't be fetched.
# Google has retired this one; picking a model from the list replaces it.
DEFAULT_GEMINI_MODEL = "gemini-1.5-flash"

# On Windows, Pillow finds FriBiDi (needed for Raqm, the right-to-left text shaping of Persian,
# Arabic and Kurdish headlines) through PATH; kernel/lib holds a bundled libfribidi-0.dll.
# This must run before PIL.ImageFont is first imported. Elsewhere FriBiDi comes from the system.
BUNDLED_LIB_DIR = os.path.join(PROJECT_ROOT, "kernel", "lib")
if sys.platform == "win32" and os.path.isdir(BUNDLED_LIB_DIR):
    os.environ["PATH"] = BUNDLED_LIB_DIR + os.pathsep + os.environ.get("PATH", "")

def load_channels_config():
    """Reads the channel configuration from _config/channels.json."""
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def get_latest_session_directory():
    """The newest session folder in _workspace (names start with a timestamp), or None.

    Used by the terminal tools when they run on their own (e.g. publisher.py, image_engine.py).
    """
    sessions = glob.glob(os.path.join(WORKSPACE_DIR, "session_*"))
    return sorted(sessions)[-1] if sessions else None

# A video post keeps its video as raw_video.<ext>, its details (duration, frame size, sound, ...)
# in video_info.json, a still frame (the "photo" the images and the area selection use) in
# video_frame.png and a small silent copy browsers can play in video_preview.mp4. All four are
# made by video_engine. Each channel's video is <channel>_broadcast.mp4.
RAW_VIDEO = "raw_video"
VIDEO_INFO = "video_info.json"
VIDEO_FRAME = "video_frame.png"
VIDEO_PREVIEW = "video_preview.mp4"

def find_raw_video(session_dir):
    """Returns the path of a video post's raw_video.* file, or None for a photo post."""
    videos = glob.glob(os.path.join(session_dir, RAW_VIDEO + ".*"))
    return videos[0] if videos else None

def load_video_info(session_dir):
    """A video post's video_info.json: video_engine.probe() details plus the frame's width and height."""
    with open(os.path.join(session_dir, VIDEO_INFO), "r", encoding="utf-8") as f:
        return json.load(f)

def input_with_timeout(prompt_text, default_value, timeout=5):
    """Terminal prompt that returns default_value (as a string) when nothing is typed within timeout seconds.

    On Windows it reads key by key with msvcrt; elsewhere it waits on stdin with select.
    """
    print(f"{prompt_text} [Auto-default: '{default_value}' in {timeout}s]: ", end='', flush=True)
    try:
        import msvcrt
        start_time = time.time()
        input_str = ""
        while True:
            if msvcrt.kbhit():
                char = msvcrt.getwch()
                if char in ('\r', '\n'):
                    print()
                    return input_str if input_str else str(default_value)
                elif char == '\b':
                    if len(input_str) > 0:
                        input_str = input_str[:-1]
                        sys.stdout.write('\b \b')
                        sys.stdout.flush()
                else:
                    input_str += char
                    sys.stdout.write(char)
                    sys.stdout.flush()
            if time.time() - start_time > timeout:
                print(f"\n  [!] Timeout. Using default: {default_value}")
                return str(default_value)
            time.sleep(0.05)
    except ImportError:
        import select
        i, o, e = select.select([sys.stdin], [], [], timeout)
        if i:
            res = sys.stdin.readline().strip("\n")
            return res if res else str(default_value)
        else:
            print(f"\n  [!] Timeout. Using default: {default_value}")
            return str(default_value)

def load_gemini_credentials():
    """{"gemini_api_key", "last_used_model"} from _credentials/gemini_keys.json.

    Without a readable file: no key, and DEFAULT_GEMINI_MODEL.
    """
    if os.path.exists(GEMINI_KEYS_FILE):
        try:
            with open(GEMINI_KEYS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"gemini_api_key": None, "last_used_model": DEFAULT_GEMINI_MODEL}

def save_gemini_credentials(api_key, model_name):
    """Writes the API key and the model to _credentials/gemini_keys.json; the model becomes the next default."""
    os.makedirs(CREDENTIALS_DIR, exist_ok=True)
    payload = {"gemini_api_key": api_key, "last_used_model": model_name}
    with open(GEMINI_KEYS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

def list_gemini_models(api_token):
    """Returns the sorted names of Gemini models that can generate text. Raises on API errors.

    Embedding, vision, live, audio and search models are left out.
    """
    from google import genai
    client = genai.Client(api_key=api_token)
    live_models = []

    for model_meta in client.models.list():
        if "gemini" in model_meta.name.lower():
            if any(bad_tag in model_meta.name.lower() for bad_tag in ["embedding", "vision", "live", "audio", "search"]):
                continue
            if "generateContent" in model_meta.supported_actions:
                clean_name = model_meta.name.split("/")[-1]
                if clean_name not in live_models:
                    live_models.append(clean_name)

    live_models.sort()
    return live_models

def select_operational_model(cached_profile):
    """Terminal menu: lists the live Gemini models, lets the user pick one and saves the choice.

    Enter (or the 5-second timeout) keeps the last used model. Without an API key, or when the
    list can't be fetched, the last used model is returned without asking. The web interface
    picks the model on its own page instead.
    """
    last_model = cached_profile.get("last_used_model", DEFAULT_GEMINI_MODEL)
    api_token = cached_profile.get("gemini_api_key")

    if not api_token:
        return last_model

    print("\n[~] Querying Google API Gateway for live intelligence clusters...")
    try:
        live_models = list_gemini_models(api_token)
    except Exception as e:
        print(f"[!] Warning: Unable to poll live registry ({e}). Defaulting to offline profile.")
        return last_model

    model_matrix = {str(i + 1): name for i, name in enumerate(live_models)}

    print("\n========================================================")
    print("  DYNAMIC GEMINI INTELLIGENCE REPOSITORY")
    print("========================================================")
    for index, name in model_matrix.items():
        display_name = name.replace("-", " ").title()
        print(f"  [{index}] {display_name} ({name})")
    print(f"  [Enter] Reuse Last Verified Default ({last_model})")
    print("========================================================")

    choice = input_with_timeout("[?] Select engine target lane", "").strip()

    selected_model = model_matrix.get(choice, last_model)
    save_gemini_credentials(api_token, selected_model)
    print(f"[OK] Pipeline routing locked to engine target: {selected_model}\n")
    return selected_model
