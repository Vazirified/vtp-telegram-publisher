import os
import re
import json
import datetime
import google.generativeai as genai

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

def get_gemini_api_token():
    """Checks for localized api token profiles or interviews the user once."""
    if not os.path.exists(CREDENTIALS_DIR):
        os.makedirs(CREDENTIALS_DIR)

    if os.path.exists(GEMINI_KEYS_FILE):
        try:
            with open(GEMINI_KEYS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data["gemini_api_key"]
        except (json.JSONDecodeError, KeyError, IOError):
            print("[!] API Token profile corrupted. Re-initializing credential gate.")

    print("+------------------------------------------------------+")
    print(":        GOOGLE AI STUDIO CORE API AUTHENTICATION      :")
    print("+------------------------------------------------------+")
    print("[i] An API Key is required to run the translation matrix.")
    print("[i] Obtain a free token here: https://aistudio.google.com")
    print("--------------------------------------------------------")

    api_key = input("[?] Paste your Gemini API Key token: ").strip()
    if not api_key:
        print("[ERROR] Token key string cannot be empty. Execution terminated.")
        exit(1)

    with open(GEMINI_KEYS_FILE, "w", encoding="utf-8") as f:
        json.dump({"gemini_api_key": api_key}, f, indent=2)

    return api_key

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
    """Sanitizes input, executes line-break paragraph parsing via Gemini, and saves files."""
    clean_text = sanitize_clipboard_text(raw_payload)
    if not clean_text:
        print("[ERROR] Input text payload resolved to empty string after sanitization pass.")
        return None

    target_languages = extract_target_languages()
    api_token = get_gemini_api_token()
    genai.configure(api_key=api_token)

    # REFINED STRUCTURAL PROMPT: Enforces the Paragraph/Newline parsing rules explicitly
    system_instruction = (
        f"You are an expert multilingual content translation engine. Your task is to process incoming text data "
        f"and output translations matching this target language array: {target_languages}.\n\n"
        f"Parsing Layout Rules:\n"
        f"1. Isolate the text into its respective provided languages.\n"
        f"2. Within each language block, the very first line or first paragraph is ALWAYS the headline. "
        f"Any text appearing after the first newline character sequence or empty line gap is the body.\n"
        f"3. If English ('en') text is missing from the input, generate it first to act as the primary master semantic reference.\n"
        f"4. For any target languages in the requested array that are missing from the input text, translate the English "
        f"headline and body into that target language, strictly maintaining the structural split rule.\n"
        f"5. Return the final data object mapping strictly to the defined schema layout containing 'headline' and 'body' string keys."
    )

    prompt = f"Process the following source content text:\n\n{clean_text}"

    print("[~] Contacting Gemini Text Gateway... Processing translation layers...")
    try:
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config={"response_mime_type": "application/json"}
        )

        response = model.generate_content([system_instruction, prompt])
        parsed_payload = json.loads(response.text)

    except Exception as e:
        print(f"[ERROR] Connection or Parsing breakdown with Gemini Engine API: {e}")
        return None

    # Step 5: Write out clean, human-readable Markdown Files in Timestamp Session Folder
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

    print("\n[SUCCESS] Text processing and compilation phase is complete.")
    return session_directory

if __name__ == "__main__":
    # Test paste completely lacking any markdown symbols, relying purely on real-world line breaks
    mock_plain_text_paste = """
    [6/8/2026 4:39 PM] Kaveh:
    Advanced Crystal Matrix Identified in Lab Test

    Researchers at the central station have successfully mapped an extraordinary crystalline molecular structural interface. This discovery changes our understanding of telemetry modules completely.

    [6/8/2026 4:41 PM] Kaveh:
    کشف ساختار ماتریس کریستالی پیشرفته در آزمایشگاه

    محققان در ایستگاه مرکزی موفق به نقشه‌برداری از یک رابط ساختاری مولکولی کریستالی فوق‌العاده شدند. این کشف درک ما را از ماژول‌های تله‌متری کاملاً تغییر می‌دهد.
    """

    execute_text_pipeline(mock_plain_text_paste)
