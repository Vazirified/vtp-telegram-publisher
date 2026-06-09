import os
import re
import json
import datetime
from google import genai
from google.genai import types

# 1. Absolute Path Layout Mappings (Unified lowercase naming standard)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
CREDENTIALS_DIR = os.path.join(PROJECT_ROOT, "_credentials")
CONFIG_FILE = os.path.join(PROJECT_ROOT, "_config", "channels.json")
WORKSPACE_DIR = os.path.join(PROJECT_ROOT, "_workspace")
GEMINI_KEYS_FILE = os.path.join(CREDENTIALS_DIR, "gemini_keys.json")

# 2. Compile Clipboard Sanitizer Regex
TELEGRAM_CLIPBOARD_REGEX = re.compile(
    r'\[\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM)?\]\s*[^:]+\s*:\s*'
)

def load_gemini_credentials():
    """Reads localized credential and model tracking profiles from disk."""
    if os.path.exists(GEMINI_KEYS_FILE):
        try:
            with open(GEMINI_KEYS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"gemini_api_key": None, "last_used_model": "gemini-1.5-flash"}

def save_gemini_credentials(api_key, model_name):
    """Saves the api key and caches the last selected model for sticky defaults."""
    if not os.path.exists(CREDENTIALS_DIR):
        os.makedirs(CREDENTIALS_DIR)

    payload = {
        "gemini_api_key": api_key,
        "last_used_model": model_name
    }
    with open(GEMINI_KEYS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

def get_gemini_api_token(cached_profile):
    """Guarantees token acquisition gate validation loops."""
    api_key = cached_profile.get("gemini_api_key")
    if api_key:
        return api_key

    print("+------------------------------------------------------+")
    print(":     GOOGLE AI STUDIO UNIFIED SDK AUTHENTICATION      :")
    print("+------------------------------------------------------+")
    api_key = input("[?] Paste your Gemini API Key token: ").strip()
    if not api_key:
        print("[ERROR] Token key string cannot be empty. Execution terminated.")
        exit(1)

    return api_key

def select_operational_model(cached_profile):
    """
    Dynamically queries Google's API for live models, filters for active
    text-generation clusters, and constructs an up-to-date choice menu.
    """
    last_model = cached_profile.get("last_used_model", "gemini-1.5-flash")
    api_token = cached_profile.get("gemini_api_key")

    if not api_token:
        return last_model

    print("\n[~] Querying Google API Gateway for live intelligence clusters...")
    try:
        client = genai.Client(api_key=api_token)
        live_models = []

        # Pull live records from Google's registry
        for model_meta in client.models.list():
            # FILTER 1: Only look at user-facing Gemini variations
            if "gemini" in model_meta.name.lower():
                # FILTER 2: Exclude utility tools (vision-only, embedding, audio streams)
                if any(bad_tag in model_meta.name.lower() for bad_tag in ["embedding", "vision", "live", "audio", "search"]):
                    continue
                # FILTER 3: Enforce text content capability
                if "generateContent" in model_meta.supported_actions:
                    clean_name = model_meta.name.split("/")[-1]
                    if clean_name not in live_models:
                        live_models.append(clean_name)

        # Sort models alphabetically so newer variations group together logically
        live_models.sort()

    except Exception as e:
        print(f"[!] Warning: Unable to poll live registry ({e}). Defaulting to offline profile.")
        return last_model

    # Build the dynamic choice matrix mapping index integers to names
    model_matrix = {str(i + 1): name for i, name in enumerate(live_models)}

    print("\n========================================================")
    print("  DYNAMIC GEMINI INTELLIGENCE REPOSITORY")
    print("========================================================")
    for index, name in model_matrix.items():
        display_name = name.replace("-", " ").title()
        print(f"  [{index}] {display_name} ({name})")
    print(f"  [Enter] Reuse Last Verified Default ({last_model})")
    print("========================================================")

    choice = input("[?] Select engine target lane: ").strip()

    selected_model = model_matrix.get(choice, last_model)
    print(f"[OK] Pipeline routing locked to engine target: {selected_model}\n")
    return selected_model

def sanitize_clipboard_text(raw_input_text: str) -> str:
    """Strips raw usernames and timestamps from the raw copy paste text."""
    cleaned = TELEGRAM_CLIPBOARD_REGEX.sub("", raw_input_text)
    return cleaned.strip()

def extract_target_languages():
    """Reads configured system targets to build a dynamic language filter list."""
    if not os.path.exists(CONFIG_FILE):
        return ["en"]
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            channels = data.get("channels", {})
            langs = list(set(info.get("language", "en") for info in channels.values()))
            if "en" not in langs:
                langs.append("en")
            return langs
    except Exception:
        return ["en"]

def execute_text_pipeline(raw_payload: str) -> str:
    """Sanitizes input, runs dynamic model routing, fires API request, and commits MDs."""
    clean_text = sanitize_clipboard_text(raw_payload)
    if not clean_text:
        print("[ERROR] Input text payload resolved to empty string after serialization pass.")
        return None

    # Step 1: Initialize credentials and pass keys safely
    cached_profile = load_gemini_credentials()
    api_token = get_gemini_api_token(cached_profile)

    # Inject token into memory to ensure first-run dynamic check succeeds
    cached_profile["gemini_api_key"] = api_token
    active_model = select_operational_model(cached_profile)

    # Commit changes permanently to disk
    save_gemini_credentials(api_token, active_model)

    target_languages = extract_target_languages()

    # Initialize the modern GenAI Client instance
    client = genai.Client(api_key=api_token)

    system_instruction = (
        f"You are an expert multilingual content translation engine. Your task is to process incoming text data "
        f"and output translations matching this target language array: {target_languages}.\n\n"
        f"Parsing Layout Rules:\n"
        f"1. Isolate the text into its respective provided languages.\n"
        f"2. Within each language block, the very first line or first paragraph is ALWAYS the headline. "
        f"Any text appearing after the first newline character sequence or empty line gap is the body.\n"
        f"3. If English ('en') text is missing from the input, generate it first to act as the primary master reference.\n"
        f"4. For any target languages in the requested array that are missing from the input text, translate the English "
        f"headline and body into that target language, strictly maintaining the structural split rule.\n"
        f"5. Return the final data object mapping strictly to the defined schema layout containing 'headline' and 'body' string keys."
    )

    prompt = f"Process the following source content text:\n\n{clean_text}"

    print(f"[~] Connecting to Unified Gateway via cluster route '{active_model}'...")
    try:
        response = client.models.generate_content(
            model=active_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json"
            )
        )
        parsed_payload = json.loads(response.text)

    except Exception as e:
        print(f"[ERROR] Unified SDK processing breakdown on route '{active_model}': {e}")
        return None

    # Step 2: Write out clean, human-readable Markdown Files in Timestamp Session Folder
    timestamp = datetime.datetime.now().strftime("session_%Y%m%d_%H%M%S")
    session_directory = os.path.join(WORKSPACE_DIR, timestamp)
    os.makedirs(session_directory, exist_ok=True)

    print(f"\n[+] Committing sole source-of-truth entries to: _workspace/{timestamp}/")
    for lang_code, content in parsed_payload.items():
        headline = content.get("headline", "").strip()
        body = content.get("body", "").strip()

        md_file_name = f"{lang_code.lower()}.md"
        md_file_path = os.path.join(session_directory, md_file_name)

        with open(md_file_path, "w", encoding="utf-8") as md_out:
            md_out.write(f"# {headline}\n\n{body}\n")

        print(f"  └─ Generated: {md_file_name} [OK]")

    print("\n[SUCCESS] Dynamic text processing core run complete.")
    return session_directory

if __name__ == "__main__":
    mock_plain_text_paste = """
    [6/9/2026 3:15 PM] Kaveh:
    Unified Dynamic Engine Successfully Implemented

    The system architecture has been updated to fully decouple the Google API client layer from static models. The model selection layout is now entirely live and fully autonomous.
    """

    execute_text_pipeline(mock_plain_text_paste)
