import os
import re
import json
import datetime
from google import genai
from google.genai import types

from common import (
    CONFIG_FILE, WORKSPACE_DIR,
    load_channels_config, load_gemini_credentials, save_gemini_credentials, select_operational_model,
)

# Compile Clipboard Sanitizer Regex
TELEGRAM_CLIPBOARD_REGEX = re.compile(
    r'\[\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM)?\]\s*[^:]+\s*:\s*'
)

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

def sanitize_clipboard_text(raw_input_text: str) -> str:
    """Strips raw usernames and timestamps from the raw copy paste text."""
    cleaned = TELEGRAM_CLIPBOARD_REGEX.sub("", raw_input_text)
    return cleaned.strip()

def extract_target_languages():
    """Reads configured system targets to build a dynamic language filter list."""
    if not os.path.exists(CONFIG_FILE):
        return ["en"]
    try:
        channels = load_channels_config().get("channels", {})
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
        f"You are an expert multilingual content translation engine that uses a economic/financial professional tone and translates every sentence given to it without leaving out any part or paragraph. Your task is to process incoming text data and output translations or parsed text data matching this target language array: {target_languages}.\n\n"
        f"Parsing Layout Rules:\n"
        f"1. Isolate the text into its respective provided languages.\n"
        f"2. Within each language block, the very first line or first paragraph is ALWAYS the headline. Any text appearing after the first newline character sequence or empty line gap is the body.\n"
        f"3. If English ('en') text is missing from the input, generate it first by combining all available data in the input text to act as the primary master reference.\n"
        f"4. For any target languages in the requested array that IS missing from the isolated language blocks, translate the English "
        f"headline and body into that target language, strictly maintaining the structural split rule. CRITICAL NOTE: If a language is not missing from the input text, DO NOT change the existing present translation provided and use it AS IS and without translation or edits in the returned output.\n"
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
        # Persists a freshly pasted key even when the model list could not be fetched
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
