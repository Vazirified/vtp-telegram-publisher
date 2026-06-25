import os
import re
import json
import datetime
import sys
import time
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
    """Dynamically queries Google's API for live models and constructs choices menu."""
    last_model = cached_profile.get("last_used_model", "gemini-1.5-flash")
    api_token = cached_profile.get("gemini_api_key")

    if not api_token:
        return last_model

    print("\n[~] Querying Google API Gateway for live intelligence clusters...")
    try:
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

    # 5-SECOND TIMEOUT APPLIED HERE
    choice = input_with_timeout("[?] Select engine target lane", "").strip()

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
    """Sanitizes inputs, runs dynamic translation matrices, and slugifies output directories."""
    clean_text = sanitize_clipboard_text(raw_payload)
    if not clean_text:
        print("[ERROR] Input text payload resolved to empty string after serialization pass.")
        return None

    cached_profile = load_gemini_credentials()
    api_token = get_gemini_api_token(cached_profile)

    cached_profile["gemini_api_key"] = api_token
    target_languages = extract_target_languages()

    system_instruction = (
        f"You are an expert multilingual content translation engine that uses a economic/financial professional tone and translates every sentence given to it without leaving out any part or paragraph. Your task is to process incoming text data and output translations matching this target language array: {target_languages}.\n\n"
        f"Parsing Layout Rules:\n"
        f"1. Isolate the text into its respective provided languages.\n"
        f"2. Within each language block, the very first line or first paragraph is ALWAYS the headline. Any text appearing after the first newline character sequence or empty line gap is the body.\n"
        f"3. If English ('en') text is missing from the input, generate it first to act as the primary master reference.\n"
        f"4. For any target languages in the requested array that are missing from the input text, translate the English "
        f"headline and body into that target language, strictly maintaining the structural split rule.\n"
        f"5. LANGUAGE SPECIAL RULE: For 'ckb' (Central Kurdish / Sorani), you MUST construct the native grammar and vocabulary using the standard Sorani Kurdo-Arabic alphabet (modified Perso-Arabic script). Characters from other languages are ABSOLUTELY FORBIDDEN. However, you ARE explicitly permitted to retain English (Latin) characters ONLY for untranslatable financial terminology, ticker symbols, proper nouns, or acronyms.\n"
        f"6. CRITICAL: The root of your output MUST be a JSON Object (dictionary), NOT a JSON Array (list). "
        f"The primary dictionary keys must be the lowercase language strings (e.g., 'en', 'fa', 'ckb').\n\n"
        f"Expected Schema Layout Format:\n"
        f"{{\n"
        f"  \"en\": {{\n"
        f"    \"headline\": \"String Text content here\",\n"
        f"    \"body\": \"String Body content paragraphs here\"\n"
        f"  }}\n"
        f"}}"
    )

    prompt = f"Process the following source content text:\n\n{clean_text}"
    parsed_payload = None

    # --- RETRY LOOP INJECTED HERE ---
    while True:
        active_model = select_operational_model(cached_profile)
        save_gemini_credentials(api_token, active_model)

        # Initialize the GenAI Client with a strict 30-second network timeout guard
        client = genai.Client(
            api_key=api_token,
            http_options=types.HttpOptions(timeout=30 * 1000) # Value in milliseconds
        )

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

            # Structural defensive layout safety handler
            if isinstance(parsed_payload, list):
                normalized_dict = {}
                for block in parsed_payload:
                    if isinstance(block, dict):
                        if "language" in block:
                            lang_key = str(block["language"]).lower()
                            normalized_dict[lang_key] = {"headline": block.get("headline", ""), "body": block.get("body", "")}
                        else:
                            for k, v in block.items():
                                if isinstance(v, dict) and ("headline" in v or "body" in v):
                                    normalized_dict[k.lower()] = v
                parsed_payload = normalized_dict

            # If everything succeeded without throwing an Exception, break the loop and continue
            break

        except Exception as e:
            print(f"\n[ERROR] Unified SDK processing breakdown on route '{active_model}': {e}")
            print("[!] The selected model is likely overloaded, unavailable, or returned bad data.")
            print("[i] Do not worry—your input text is safe. Returning to the model selection menu.")
            print("    (Press Ctrl+C to abort entirely if you wish to exit)\n")

    # Step 5: Format the English headline into a human-readable folder slug string
    en_node = parsed_payload.get("en", {})
    en_headline = en_node.get("headline", "untitled-post")

    # Process text layout into clean URL-safe dash formatting
    slug = en_headline.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)  # Drop special characters/punctuation
    slug = re.sub(r'[\s-]+', '-', slug)        # Map whitespace sequences down into single dashes
    slug = slug.strip('-')                     # Clear off dangling boundaries

    timestamp = datetime.datetime.now().strftime("session_%Y%m%d_%H%M%S")
    folder_name = f"{timestamp}_{slug}" if slug else timestamp

    session_directory = os.path.join(WORKSPACE_DIR, folder_name)
    os.makedirs(session_directory, exist_ok=True)

    print(f"\n[+] Committing sole source-of-truth entries to: _workspace/{folder_name}/")
    for lang_code, content in parsed_payload.items():
        if not isinstance(content, dict):
            continue

        headline = content.get("headline", "").strip()
        body = content.get("body", "").strip()

        md_file_name = f"{lang_code.lower()}.md"
        md_file_path = os.path.join(session_directory, md_file_name)

        with open(md_file_path, "w", encoding="utf-8") as md_out:
            md_out.write(f"# {headline}\n\n{body}\n")

        print(f" -> Generated: {md_file_name} [OK]")

    print("\n[SUCCESS] Dynamic text processing core run complete.")
    return session_directory

if __name__ == "__main__":
    mock_plain_text_paste = """
    [6/9/2026 3:15 PM] Kaveh:
    Unified Dynamic Engine Successfully Implemented

    The system architecture has been updated to fully decouple the Google API client layer from static models. The model selection layout is now entirely live and fully autonomous.
    """
    execute_text_pipeline(mock_plain_text_paste)
