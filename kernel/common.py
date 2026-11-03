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

DEFAULT_GEMINI_MODEL = "gemini-1.5-flash"

# On Windows, Pillow finds FriBiDi (needed for Raqm text shaping) through PATH.
# This must run before PIL.ImageFont is first imported.
BUNDLED_LIB_DIR = os.path.join(PROJECT_ROOT, "kernel", "lib")
if sys.platform == "win32" and os.path.isdir(BUNDLED_LIB_DIR):
    os.environ["PATH"] = BUNDLED_LIB_DIR + os.pathsep + os.environ.get("PATH", "")

def load_channels_config():
    """Reads the channel configuration from _config/channels.json."""
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def get_latest_session_directory():
    """Locates the latest session folder within the workspace."""
    sessions = glob.glob(os.path.join(WORKSPACE_DIR, "session_*"))
    return sorted(sessions)[-1] if sessions else None

def input_with_timeout(prompt_text, default_value, timeout=5):
    """Cross-platform input with a timeout and default fallback."""
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
    """Reads the cached Gemini API key and last used model from disk."""
    if os.path.exists(GEMINI_KEYS_FILE):
        try:
            with open(GEMINI_KEYS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"gemini_api_key": None, "last_used_model": DEFAULT_GEMINI_MODEL}

def save_gemini_credentials(api_key, model_name):
    """Saves the API key and caches the last selected model for sticky defaults."""
    os.makedirs(CREDENTIALS_DIR, exist_ok=True)
    payload = {"gemini_api_key": api_key, "last_used_model": model_name}
    with open(GEMINI_KEYS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

def select_operational_model(cached_profile):
    """Lists live Gemini models, lets the user pick one, and caches the choice."""
    last_model = cached_profile.get("last_used_model", DEFAULT_GEMINI_MODEL)
    api_token = cached_profile.get("gemini_api_key")

    if not api_token:
        return last_model

    print("\n[~] Querying Google API Gateway for live intelligence clusters...")
    try:
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
