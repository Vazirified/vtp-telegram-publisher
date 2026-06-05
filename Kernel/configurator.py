import os
import json

# 1. Dynamically compute the absolute path to the project root directory.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

# 2. Define target directory paths with clean lowercase and "_" prefix, anchored to project root.
REQUIRED_DIRS = [
    os.path.join(PROJECT_ROOT, "_config"),
    os.path.join(PROJECT_ROOT, "_config", "templates"),
    os.path.join(PROJECT_ROOT, "_config", "fonts"),
    os.path.join(PROJECT_ROOT, "_workspace"),
    os.path.join(PROJECT_ROOT, "_credentials")
]
CONFIG_FILE = os.path.join(PROJECT_ROOT, "_config", "channels.json")

def bootstrap_environment():
    """
    Verifies and builds the complete required directory layout if missing.
    Ensures stateless test cleanups do not break execution loops.
    """
    for directory in REQUIRED_DIRS:
        if not os.path.exists(directory):
            os.makedirs(directory)
            rel_path = os.path.relpath(directory, PROJECT_ROOT)
            print(f"[+] Recreated missing directory: {rel_path}")

def load_config():
    """
    Reads the channel master registry from disk. Returns a base template if empty.
    """
    if not os.path.exists(CONFIG_FILE):
        return {"channels": {}}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        print("[!] Error reading channels.json. Initializing clean registry structure.")
        return {"channels": {}}

def save_config(config_data):
    """
    Writes the updated channel registry back to channels.json.
    """
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
        print("[OK] Configuration saved successfully.")
    except IOError as e:
        print(f"[ERROR] Failed to commit changes to disk: {e}")

def prompt_layout_config(channel_key, existing_layout=None):
    """
    Interactive terminal sub-wizard to configure coordinates, spacing,
    bounding box limits, and typography/alignment variables.
    """
    layout = existing_layout or {}
    print(f"\n--- Image Layout Settings for {channel_key} ---")

    layout["canvas_size"] = [1000, 1000]
    print("[i] Output target resolution is locked to 1000x1000 pixels.")

    print("\nSelect Canvas Preset Profile:")
    print("  [1] Standard Top Frame    (1000x680 area with smart crop)")
    print("  [2] Slim Top Frame        (1000x655 area with smart crop)")
    print("  [3] Extended Top Frame    (1000x780 area with smart crop)")
    print("  [4] Full-Bleed Background  (1000x1000 full coverage layout)")
    print("  [5] Custom Coordinates Manual Override")
    preset_choice = input("[?] Select baseline preset [1-5]: ").strip()

    raw_placement = layout.get("raw_image_placement", {})
    raw_placement["resize_mode"] = "cover"

    if preset_choice == "1":
        raw_placement.update({"x": 0, "y": 0, "width": 1000, "height": 680})
    elif preset_choice == "2":
        raw_placement.update({"x": 0, "y": 0, "width": 1000, "height": 655})
    elif preset_choice == "3":
        raw_placement.update({"x": 0, "y": 0, "width": 1000, "height": 780})
    elif preset_choice == "4":
        raw_placement.update({"x": 0, "y": 0, "width": 1000, "height": 1000})
    else:
        print("\nEnter custom background boundaries (in pixels):")
        raw_placement["x"] = int(input("    X coordinate: ") or 0)
        raw_placement["y"] = int(input("    Y coordinate: ") or 0)
        raw_placement["width"] = int(input("    Target Width: ") or 1000)
        raw_placement["height"] = int(input("    Target Height: ") or 700)

    layout["raw_image_placement"] = raw_placement

    default_overlay = f"_config/templates/{channel_key}_overlay.png"
    overlay_input = input(f"[?] Branding Overlay PNG Path [Default: {default_overlay}]: ").strip()
    layout["template_overlay_path"] = overlay_input if overlay_input else default_overlay

    safe_area = layout.get("headline_safe_area", {})
    print("\nConfigure Headline Safe Area Boundary Box:")
    safe_area["x_start"] = int(input(f"    Bounding Box X Start [Current: {safe_area.get('x_start', 50)}]: ") or safe_area.get("x_start", 50))
    safe_area["y_start"] = int(input(f"    Bounding Box Y Start [Current: {safe_area.get('y_start', 750)}]: ") or safe_area.get("y_start", 750))
    safe_area["width"] = int(input(f"    Bounding Box Width   [Current: {safe_area.get('width', 900)}]: ") or safe_area.get("width", 900))
    safe_area["max_height"] = int(input(f"    Bounding Box Max H   [Current: {safe_area.get('max_height', 200)}]: ") or safe_area.get("max_height", 200))

    print("\nConfigure Typography Profile:")
    default_font = f"_config/fonts/{channel_key}_font.ttf"
    font_input = input(f"    Font Path (.ttf file) [Current: {safe_area.get('font_path', default_font)}]: ").strip()
    safe_area["font_path"] = font_input if font_input else safe_area.get("font_path", default_font)
    safe_area["font_size"] = int(input(f"    Base Font Size Pt     [Current: {safe_area.get('font_size', 44)}]: ") or safe_area.get("font_size", 44))
    safe_area["font_color"] = input(f"    Hex Font Color Code   [Current: {safe_area.get('font_color', '#FFFFFF')}]: ").strip() or safe_area.get("font_color", "#FFFFFF")

    print("\nSelect Headline Horizontal Alignment Rule:")
    print("  [1] Left Alignment")
    print("  [2] Center Alignment")
    print("  [3] Right Alignment")
    align_choice = input("[?] Choose layout alignment [1-3]: ").strip()

    if align_choice == "1":
        safe_area["alignment"] = "left"
    elif align_choice == "2":
        safe_area["alignment"] = "center"
    elif align_choice == "3":
        safe_area["alignment"] = "right"
    else:
        safe_area["alignment"] = safe_area.get("alignment", "left")

    layout["headline_safe_area"] = safe_area
    return layout

def prompt_caption_config(channel_key, existing_caption=None):
    """
    Provides a free-form text template onboarding terminal for headers
    and footers supporting dynamic content syntax placeholders.
    """
    caps = existing_caption or {}
    print(f"\n--- Free-Form Caption Templates for {channel_key} ---")
    print("  +----------------------------------------------------------------+")
    print("  : FORMATTING RULES REFERENCE:                                    :")
    print("  : Use {headline} to place the parsed title string.                :")
    print("  : Use {channel} to inject the channel identifier link.           :")
    print("  : Use [eid:64BitID] to render premium custom animated emojis.     :")
    print("  : Extraction Tool: .venv\\Scripts\\python kernel\\inspect_emoji.py  :")
    print("  +----------------------------------------------------------------+")

    default_hdr = "⚠️ [eid:5368324170671202286] BREAKING: {headline}"
    default_ftr = "📣 Follow updates on {channel} [eid:543216789012345]"

    print(f"\n[i] Example Header String: {default_hdr}")
    hdr_input = input(f"[?] Enter Header Template Line\n    [Current: {caps.get('header_template', 'Blank')}]: ").strip()
    caps["header_template"] = hdr_input if hdr_input else caps.get("header_template", "")

    print(f"\n[i] Example Footer String: {default_ftr}")
    ftr_input = input(f"[?] Enter Footer Template Line\n    [Current: {caps.get('footer_template', 'Blank')}]: ").strip()
    caps["footer_template"] = ftr_input if ftr_input else caps.get("footer_template", "")

    return caps

def add_or_modify_channel(channel_key=None):
    """
    Assembles configuration schema nodes. Adds a fresh channel entry or
    overwrites properties of an existing channel reference key.
    """
    config_data = load_config()
    is_new = channel_key is None

    if is_new:
        print("\n=== Registering New Target Channel ===")
        channel_key = input("[?] Internal reference name (e.g., eplanet_fa_news): ").strip().lower()
        if not channel_key:
            print("[ERROR] Identity key cannot be empty. Aborting channel registration.")
            return
        if channel_key in config_data["channels"]:
            print(f"[!] Target reference profile key '{channel_key}' already exists. Shifting to update mode.")
            is_new = False

    profile = config_data["channels"].get(channel_key, {})

    print(f"\nEditing attributes for: {channel_key}")
    profile["chat_id"] = input(f"[?] Telegram Public ID/Chat Entity [Current: {profile.get('chat_id', '@eplanet')}]: ").strip() or profile.get("chat_id", "@eplanet")
    profile["language"] = input(f"[?] Channel Language Code ISO (e.g., fa, ku, en) [Current: {profile.get('language', 'en')}]: ").strip().lower() or profile.get("language", "en")

    rtl_prompt = input(f"[?] Is this a Right-To-Left (RTL) language layout? (y/n) [Current: {profile.get('is_rtl', False)}]: ").strip().lower()
    if rtl_prompt:
        profile["is_rtl"] = True if rtl_prompt in ['y', 'yes'] else False
    elif "is_rtl" not in profile:
        profile["is_rtl"] = False

    profile["image_layout"] = prompt_layout_config(channel_key, profile.get("image_layout"))
    profile["caption_settings"] = prompt_caption_config(channel_key, profile.get("caption_settings"))

    config_data["channels"][channel_key] = profile
    save_config(config_data)

def display_channels():
    """
    Prints a clear overview table listing currently configured publishing targets.
    """
    config_data = load_config()
    channels = config_data.get("channels", {})

    print("\n========================================================")
    print("  CURRENTLY DEFINED CHANNELS REGISTRY")
    print("========================================================")
    if not channels:
        print("  [i] No target channels registered inside channels.json.")
    else:
        for key, info in channels.items():
            align = info.get("image_layout", {}).get("headline_safe_area", {}).get("alignment", "N/A")
            rtl_flag = "[RTL]" if info.get("is_rtl") else "[LTR]"
            hdr_str = info.get("caption_settings", {}).get("header_template", "None")
            print(f"  Reference Key : {key}")
            print(f"  Telegram ID   : {info.get('chat_id')}")
            print(f"  Lang Identity : {info.get('language')} {rtl_flag} | Text Align: {align}")
            print(f"  Header Config : {hdr_str}")
            print("  ------------------------------------------------------")
    print("========================================================\n")

def interactive_console():
    """
    The main shell loop. Exposes basic management choices to the terminal operator.
    """
    bootstrap_environment()

    if not os.path.exists(CONFIG_FILE) or not load_config().get("channels"):
        print("[!] Channel configuration registry missing or empty.")
        print("[-->] Automatically starting initial channel configuration wizard...")
        add_or_modify_channel()

    while True:
        print("========================================================")
        print("  ePLANET PUBLISHER ADMINISTRATIVE CONFIGURATOR")
        print("========================================================")
        print("  1. List Registered Publishing Channels")
        print("  2. Add a Brand New Channel Target Profile")
        print("  3. Modify an Existing Channel Configuration")
        print("  4. Remove a Channel Profile Reference")
        print("  5. Exit Console Engine")
        print("========================================================")
        choice = input("[?] Choose operations option [1-5]: ").strip()

        if choice == "1":
            display_channels()
        elif choice == "2":
            add_or_modify_channel()
        elif choice == "3":
            display_channels()
            key_to_mod = input("[?] Input target reference key to modify: ").strip().lower()
            config_data = load_config()
            if key_to_mod in config_data["channels"]:
                add_or_modify_channel(key_to_mod)
            else:
                print(f"[ERROR] Reference tracking key '{key_to_mod}' not found.")
        elif choice == "4":
            display_channels()
            key_to_del = input("[?] Input target reference key to erase: ").strip().lower()
            config_data = load_config()
            if key_to_del in config_data["channels"]:
                confirm = input(f"[!] Are you sure you want to delete '{key_to_del}'? (y/n): ").strip().lower()
                if confirm in ['y', 'yes']:
                    del config_data["channels"][key_to_del]
                    save_config(config_data)
                    print(f"[OK] Profile entry '{key_to_del}' dropped.")
            else:
                print(f"[ERROR] Reference tracking key '{key_to_del}' not found.")
        elif choice == "5":
            print("\n[-->] Closing administrative control terminal context.")
            break
        else:
            print("[!] Invalid action choice pattern. Please select 1 through 5.")
        print("\n")

if __name__ == "__main__":
    interactive_console()
