import os
import json
import shutil

# 1. Project-wide absolute path mapping aligned with auth_manager
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

CREDENTIALS_DIR = os.path.join(PROJECT_ROOT, "_credentials")
CONFIG_DIR = os.path.join(PROJECT_ROOT, "_config")
WORKSPACE_DIR = os.path.join(PROJECT_ROOT, "_workspace")
CONFIG_FILE = os.path.join(CONFIG_DIR, "channels.json")

REQUIRED_DIRS = [
    CONFIG_DIR,
    os.path.join(CONFIG_DIR, "templates"),
    os.path.join(CONFIG_DIR, "fonts"),
    WORKSPACE_DIR,
    CREDENTIALS_DIR
]

def bootstrap_environment():
    """Verifies and structures the folder workspace environment cleanly."""
    for directory in REQUIRED_DIRS:
        if not os.path.exists(directory):
            os.makedirs(directory)
            print(f"[+] Created directory: {directory}")

def load_config():
    """Reads configuration payload from disk. Enforces foundational schema maps."""
    default_schema = {"catch_all_channel": None, "channels": {}}
    if not os.path.exists(CONFIG_FILE):
        return default_schema
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "catch_all_channel" not in data:
                data["catch_all_channel"] = None
            if "channels" not in data:
                data["channels"] = {}
            return data
    except (json.JSONDecodeError, IOError):
        return default_schema

def save_config(config_data):
    """Commits system runtime configurations back cleanly to disk."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
        print("[OK] Configuration state successfully committed.")
    except IOError as e:
        print(f"[ERROR] Disk write failure: {e}")

def choose_asset_file(relative_dir, extensions, asset_name, default_fallback):
    """Dynamically lists available assets and allows file selection or external import."""
    abs_dir = os.path.join(PROJECT_ROOT, relative_dir)
    if not os.path.exists(abs_dir):
        os.makedirs(abs_dir, exist_ok=True)

    files = [f for f in os.listdir(abs_dir) if f.lower().endswith(tuple(extensions))]

    print(f"\nSelect {asset_name}:")
    if not files:
        print(f"  [i] No files found in {relative_dir}/")
    else:
        for i, f in enumerate(files, 1):
            print(f"  [{i}] {f}")

    custom_idx = len(files) + 1
    print(f"  [{custom_idx}] Provide custom path (will be automatically imported to {relative_dir}/)")

    choice = input(f"[?] Choose an option [1-{custom_idx}] [Current/Default: {default_fallback}]: ").strip()

    if not choice:
        return default_fallback

    if choice.isdigit():
        idx = int(choice)
        if 1 <= idx <= len(files):
            return f"{relative_dir}/{files[idx-1]}"
        elif idx == custom_idx:
            custom_path = input(f"    -> Enter full absolute path to your file: ").strip()
            custom_path = custom_path.strip("\"'")
            if os.path.exists(custom_path):
                filename = os.path.basename(custom_path)
                dest_path = os.path.join(abs_dir, filename)
                try:
                    shutil.copy2(custom_path, dest_path)
                    print(f"    [+] Successfully imported '{filename}' into {relative_dir}/")
                    return f"{relative_dir}/{filename}"
                except Exception as e:
                    print(f"    [ERROR] Failed to copy file: {e}. Falling back to default.")
                    return default_fallback
            else:
                print(f"    [!] File not found at '{custom_path}'. Falling back to default.")
                return default_fallback

    return default_fallback

def configure_global_catch_all():
    """Dedicated management wizard for handling the review gate identity."""
    config_data = load_config()
    current_gate = config_data.get("catch_all_channel")

    print("\n=== Global Catch-All (Review Gate) Configuration ===")
    print(f"  Current Gate Target: {current_gate if current_gate else 'DISABLED (Direct Publishing Live)'}")
    print("--------------------------------------------------------")
    print("  When active, ALL formatted image/caption variants are sent here first")
    print("  for human verification before distribution loops run.")
    print("--------------------------------------------------------")

    choice = input("[?] Enable/Modify review staging gate? (y/n): ").strip().lower()
    if choice in ['y', 'yes']:
        new_gate = input("[?] Enter Staging Channel Telegram ID (e.g., @eplanet_staging): ").strip()
        if new_gate:
            config_data["catch_all_channel"] = new_gate
            save_config(config_data)
        else:
            print("[!] Invalid input. Staging gate state unchanged.")
    else:
        disable_choice = input("[?] Completely disable review gating? (y/n): ").strip().lower()
        if disable_choice in ['y', 'yes']:
            config_data["catch_all_channel"] = None
            save_config(config_data)
            print("[OK] Review staging gate deactivated. Content will publish directly.")

def prompt_layout_config(channel_key, existing_layout=None):
    layout = existing_layout or {}
    print(f"\n--- Image Layout Settings for {channel_key} ---")
    layout["canvas_size"] = [1000, 1000]

    print("\nSelect Canvas Preset Profile:")
    print("  [1] Arabic TV & Broker              (975x760 area with smart crop)")
    print("  [2] Persian Teampro                 (980x660 area with smart crop)")
    print("  [3] Persian Broker & Kurdish Broker (1000x676 area with smart crop)")
    print("  [4] English Broker                  (1000x1000 full coverage layout)")
    print("  [5] Persian TV                      (1000x1000 full coverage layout)")
    print("  [6] Custom Coordinates Manual Override")
    preset_choice = input("[?] Select baseline preset [1-6]: ").strip()

    raw_placement = layout.get("raw_image_placement", {})
    raw_placement["resize_mode"] = "cover"

    if preset_choice == "1":
        raw_placement.update({"x": 14, "y": 14, "width": 975, "height": 760})
    elif preset_choice == "2":
        raw_placement.update({"x": 10, "y": 10, "width": 980, "height": 660})
    elif preset_choice == "3":
        raw_placement.update({"x": 0, "y": 0, "width": 1000, "height": 676})
    elif preset_choice == "4":
        raw_placement.update({"x": 0, "y": 0, "width": 1000, "height": 465})
    elif preset_choice == "5":
        raw_placement.update({"x": 0, "y": 0, "width": 1000, "height": 1000})
    else:
        print("\nEnter custom background boundaries (in pixels):")
        raw_placement["x"] = int(input("    X coordinate: ") or 0)
        raw_placement["y"] = int(input("    Y coordinate: ") or 0)
        raw_placement["width"] = int(input("    Target Width: ") or 1000)
        raw_placement["height"] = int(input("    Target Height: ") or 700)

    layout["raw_image_placement"] = raw_placement

    default_overlay = layout.get("template_overlay_path", f"_config/templates/{channel_key}_overlay.png")
    layout["template_overlay_path"] = choose_asset_file(
        "_config/templates",
        ['.png', '.jpg', '.jpeg'],
        "Branding Overlay Template",
        default_overlay
    )

    safe_area = layout.get("headline_safe_area", {})
    print("\nConfigure Headline Safe Area Boundary Box:")
    print("  [1] Persian Broker")
    print("  [2] Persian TeamPro")
    print("  [3] Persian TV")
    print("  [4] Arabic Broker")
    print("  [5] English Broker")
    print("  [6] Kurdish Broker")
    print("  [7] Arabic TV")
    print("  [8] Custom Manual Coordinates...")
    area_choice = input("[?] Choose safe area profile [1-8]: ").strip()

    if area_choice == "1":
        safe_area["x_start"] = 48
        safe_area["y_start"] = 710
        safe_area["width"] = 905
        safe_area["max_height"] = 250
    elif area_choice == "2":
        safe_area["x_start"] = 36
        safe_area["y_start"] = 700
        safe_area["width"] = 930
        safe_area["max_height"] = 195
    elif area_choice == "3":
        safe_area["x_start"] = 60
        safe_area["y_start"] = 780
        safe_area["width"] = 880
        safe_area["max_height"] = 185
    elif area_choice == "4":
        safe_area["x_start"] = 39
        safe_area["y_start"] = 795
        safe_area["width"] = 920
        safe_area["max_height"] = 120
    elif area_choice == "5":
        safe_area["x_start"] = 54
        safe_area["y_start"] = 690
        safe_area["width"] = 890
        safe_area["max_height"] = 210
    elif area_choice == "6":
        safe_area["x_start"] = 60
        safe_area["y_start"] = 700
        safe_area["width"] = 880
        safe_area["max_height"] = 270
    elif area_choice == "7":
        safe_area["x_start"] = 50
        safe_area["y_start"] = 790
        safe_area["width"] = 905
        safe_area["max_height"] = 190
    else:
        print("\n[i] Enter custom coordinates in pixels:")
        safe_area["x_start"] = int(input(f"    Bounding Box X Start [Current: {safe_area.get('x_start', 50)}]: ") or safe_area.get("x_start", 50))
        safe_area["y_start"] = int(input(f"    Bounding Box Y Start [Current: {safe_area.get('y_start', 750)}]: ") or safe_area.get("y_start", 750))
        safe_area["width"] = int(input(f"    Bounding Box Width   [Current: {safe_area.get('width', 900)}]: ") or safe_area.get("width", 900))
        safe_area["max_height"] = int(input(f"    Bounding Box Max H   [Current: {safe_area.get('max_height', 200)}]: ") or safe_area.get("max_height", 200))

    print(f"    -> Safe Area Set: {safe_area['width']}x{safe_area['max_height']} at ({safe_area['x_start']}, {safe_area['y_start']})")

    default_font = safe_area.get("font_path", "_config/fonts/Dana-Medium.ttf")
    safe_area["font_path"] = choose_asset_file(
        "_config/fonts",
        ['.ttf', '.otf'],
        "Typography Font File",
        default_font
    )

    safe_area["font_size"] = int(input(f"\n    Base Font Size Pt     [Current: {safe_area.get('font_size', 44)}]: ") or safe_area.get("font_size", 44))
    safe_area["font_color"] = input(f"    Hex Font Color Code   [Current: {safe_area.get('font_color', '#FFFFFF')}]: ").strip() or safe_area.get("font_color", "#FFFFFF")

    print("\nSelect Font Weight:")
    print("  [1] Regular | [2] Semi-Bold | [3] Bold")
    weight_choice = input(f"[?] Choose font weight [1-3] [Current: {safe_area.get('font_weight', 'regular')}]: ").strip()
    if weight_choice == "1": safe_area["font_weight"] = "regular"
    elif weight_choice == "2": safe_area["font_weight"] = "semi-bold"
    elif weight_choice == "3": safe_area["font_weight"] = "bold"
    else: safe_area["font_weight"] = safe_area.get("font_weight", "regular")

    print("\nSelect Text Justification / Alignment:")
    print("  [1] Left | [2] Center | [3] Right")
    align_choice = input(f"[?] Choose justification [1-3] [Current: {safe_area.get('alignment', 'center')}]: ").strip()
    if align_choice == "1": safe_area["alignment"] = "left"
    elif align_choice == "2": safe_area["alignment"] = "center"
    elif align_choice == "3": safe_area["alignment"] = "right"
    else: safe_area["alignment"] = safe_area.get("alignment", "center")

    layout["headline_safe_area"] = safe_area
    return layout

def prompt_caption_config(channel_key, existing_caption=None):
    caps = existing_caption or {}
    print(f"\n--- Free-Form Caption Templates for {channel_key} ---")
    hdr_input = input(f"[?] Enter Header Template Line\n    [Current: {caps.get('header_template', 'Blank')}]: ").strip()
    caps["header_template"] = hdr_input if hdr_input else caps.get("header_template", "")
    ftr_input = input(f"[?] Enter Footer Template Line\n    [Current: {caps.get('footer_template', 'Blank')}]: ").strip()
    caps["footer_template"] = ftr_input if ftr_input else caps.get("footer_template", "")
    return caps

def add_or_modify_channel(channel_key=None):
    config_data = load_config()
    is_new = channel_key is None

    if is_new:
        print("\n=== Registering New Target Channel ===")
        channel_key = input("[?] Internal reference name (e.g., fa_news): ").strip().lower()
        if not channel_key: return
        if channel_key in config_data["channels"]: is_new = False

    profile = config_data["channels"].get(channel_key, {})
    profile["chat_id"] = input(f"[?] Telegram Public ID/Chat Entity [Current: {profile.get('chat_id', '@eplanet')}]: ").strip() or profile.get("chat_id", "@eplanet")
    profile["language"] = input(f"[?] Channel Language Code ISO [Current: {profile.get('language', 'en')}]: ").strip().lower() or profile.get("language", "en")

    rtl_prompt = input(f"[?] Is this a Right-To-Left (RTL) layout? (y/n) [Current: {profile.get('is_rtl', False)}]: ").strip().lower()
    profile["is_rtl"] = True if rtl_prompt in ['y', 'yes'] else (profile.get('is_rtl', False) if not rtl_prompt else False)

    profile["image_layout"] = prompt_layout_config(channel_key, profile.get("image_layout"))
    profile["caption_settings"] = prompt_caption_config(channel_key, profile.get("caption_settings"))

    config_data["channels"][channel_key] = profile
    save_config(config_data)

def display_channels():
    config_data = load_config()
    channels = config_data.get("channels", {})
    gate = config_data.get("catch_all_channel")

    print("\n========================================================")
    print("  LIVE DISTRIBUTION REGISTRY STATUS")
    print("========================================================")
    print(f"  GLOBAL STAGING REVIEW GATE : {gate if gate else 'DISABLED (Direct Mode)'}")
    print("========================================================")
    if not channels:
        print("  [i] No target publishing language channels registered.")
    else:
        for key, info in channels.items():
            align = info.get("image_layout", {}).get("headline_safe_area", {}).get("alignment", "N/A")
            rtl_flag = "[RTL]" if info.get("is_rtl") else "[LTR]"
            print(f"  Reference Key : {key}")
            print(f"  Telegram ID   : {info.get('chat_id')}")
            print(f"  Config Target : {info.get('language')} {rtl_flag} | Alignment: {align}")
            print("  ------------------------------------------------------")
    print("========================================================\n")

def interactive_console():
    bootstrap_environment()
    while True:
        print("========================================================")
        print("  ePLANET PUBLISHER ADMINISTRATIVE CONFIGURATOR")
        print("========================================================")
        print("  1. List Profile Registries & Staging Status")
        print("  2. Add a Brand New Channel Target Profile")
        print("  3. Modify an Existing Channel Configuration")
        print("  4. Remove a Channel Profile Reference")
        print("  5. Configure Global Catch-All Review Gate")
        print("  6. Exit Console Engine")
        print("========================================================")
        choice = input("[?] Choose operations option [1-6]: ").strip()

        if choice == "1": display_channels()
        elif choice == "2": add_or_modify_channel()
        elif choice == "3":
            display_channels()
            key_to_mod = input("[?] Input reference key to modify: ").strip().lower()
            if key_to_mod in load_config()["channels"]: add_or_modify_channel(key_to_mod)
        elif choice == "4":
            display_channels()
            key_to_del = input("[?] Input reference key to erase: ").strip().lower()
            config_data = load_config()
            if key_to_del in config_data["channels"]:
                if input(f"[!] Erase '{key_to_del}'? (y/n): ").strip().lower() in ['y', 'yes']:
                    del config_data["channels"][key_to_del]
                    save_config(config_data)
        elif choice == "5": configure_global_catch_all()
        elif choice == "6": break
        print("\n")

if __name__ == "__main__":
    interactive_console()
