import os
import json

from PIL import Image

from common import PROJECT_ROOT, CONFIG_FILE

CONFIG_DIR = os.path.dirname(CONFIG_FILE)

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {"catch_all_channel": "", "channels": {}}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(config):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print("\n[+] Configuration saved successfully!")

def prompt(text, default=None, cast_type=str):
    default_text = f" [{default}]" if default is not None else ""
    while True:
        val = input(f"{text}{default_text}: ").strip()
        if not val and default is not None:
            return default
        if not val and default is None:
            if cast_type == str: return ""
            print("  [!] This field is required.")
            continue
        try:
            if cast_type == bool:
                return val.lower() in ['true', 't', 'y', 'yes', '1']
            return cast_type(val)
        except ValueError:
            print(f"  [!] Invalid input. Please enter a valid {cast_type.__name__}.")

def choose_asset(subdir, extensions, label, current=None):
    """Lists the files in _config/<subdir> and returns the chosen one as a project-relative path."""
    folder = os.path.join(CONFIG_DIR, subdir)
    files = sorted(f for f in os.listdir(folder) if f.lower().endswith(extensions)) if os.path.isdir(folder) else []

    print(f"\n{label} (from _config/{subdir}/):")
    for i, name in enumerate(files, 1):
        print(f"  [{i}] {name}")
    if not files:
        print(f"  [i] No files found in _config/{subdir}/")

    while True:
        choice = prompt("Choose a number or type a path", current)
        if choice.isdigit() and 1 <= int(choice) <= len(files):
            return f"_config/{subdir}/{files[int(choice) - 1]}"
        if choice and os.path.isfile(os.path.join(PROJECT_ROOT, choice)):
            return choice
        print(f"  [!] '{choice}' is not a listed number or an existing file.")

def template_canvas_size(template_path, fallback):
    """The canvas must match the template's pixel size, or the overlay cannot be composited."""
    try:
        with Image.open(os.path.join(PROJECT_ROOT, template_path)) as img:
            size = list(img.size)
        print(f"  [i] Canvas size set to {size[0]}x{size[1]} to match the template.")
        return size
    except OSError as e:
        print(f"  [!] Could not read the template ({e}). Keeping canvas size {fallback[0]}x{fallback[1]}.")
        return fallback

def configure_channel(existing=None):
    existing = existing or {}
    layout = existing.get("image_layout", {})
    safe_area = layout.get("headline_safe_area", {})
    raw_placement = layout.get("raw_image_placement", {})
    captions = existing.get("caption_settings", {})

    print("\n--- 1. Channel Basics ---")
    chat_id = prompt("Chat ID / Username (e.g., @eplanet_teampro)", existing.get("chat_id", ""))
    lang = prompt("Language code (e.g., fa, en, ar, ckb)", existing.get("language", "fa"))
    is_rtl = prompt("Is RTL layout? (True/False)", existing.get("is_rtl", True), bool)

    print("\n--- 2. Image Layout: Raw Photo/Chart Placement ---")
    rx = prompt("Raw Image X position", raw_placement.get("x", 10), int)
    ry = prompt("Raw Image Y position", raw_placement.get("y", 10), int)
    rw = prompt("Raw Image Width", raw_placement.get("width", 980), int)
    rh = prompt("Raw Image Height", raw_placement.get("height", 660), int)

    print("\n--- 3. Image Layout: Template & Typography ---")
    template = choose_asset("templates", (".png",), "Template Overlay", layout.get("template_overlay_path"))
    canvas_size = template_canvas_size(template, layout.get("canvas_size", [1000, 1000]))

    sx = prompt("Text Safe Area X Start", safe_area.get("x_start", 36), int)
    sy = prompt("Text Safe Area Y Start", safe_area.get("y_start", 700), int)
    sw = prompt("Text Safe Area Width", safe_area.get("width", 930), int)
    sh = prompt("Text Safe Area Max Height", safe_area.get("max_height", 195), int)

    font_path = choose_asset("fonts", (".ttf", ".otf"), "Headline Font", safe_area.get("font_path", "_config/fonts/Dana-Medium.ttf"))
    font_size = prompt("Base Font Size", safe_area.get("font_size", 48), int)
    font_color = prompt("Font Color (Hex Code)", safe_area.get("font_color", "#ffffff"))
    alignment = prompt("Text Alignment (left/center/right)", safe_area.get("alignment", "center"))

    # Updated default to 1.1
    line_spacing = prompt("Line Spacing Multiplier", safe_area.get("line_spacing", 1.1), float)
    max_lines = prompt("Max Allowed Lines", safe_area.get("max_lines", 2), int)

    print("\n--- 4. Telegram Caption Formatting ---")
    print("(Note: Type \\n literally for line breaks)")
    header = prompt("Header Template HTML", captions.get("header_template", ""))
    footer = prompt("Footer Template HTML", captions.get("footer_template", ""))

    return {
        "chat_id": chat_id,
        "language": lang,
        "is_rtl": is_rtl,
        "image_layout": {
            "canvas_size": canvas_size,
            "raw_image_placement": {
                "x": rx, "y": ry, "width": rw, "height": rh
            },
            "template_overlay_path": template,
            "headline_safe_area": {
                "x_start": sx, "y_start": sy, "width": sw, "max_height": sh,
                "font_path": font_path, "font_size": font_size, "font_color": font_color,
                "alignment": alignment,
                "line_spacing": line_spacing,
                "max_lines": max_lines
            }
        },
        "caption_settings": {
            "header_template": header,
            "footer_template": footer
        }
    }

def main():
    config = load_config()

    while True:
        print("\n" + "="*40)
        print(" EPLANET TELEGRAM PUBLISHER CONFIGURATOR")
        print("="*40)
        print("1. Add a New Channel")
        print("2. Edit an Existing Channel")
        print("3. Delete a Channel")
        print("4. View Active Channels")
        print("5. Configure Global Catch-All Review Gate")
        print("0. Save & Exit")

        choice = input("\nSelect an option: ").strip()

        if choice == '1':
            ch_name = input("Enter new internal channel name (e.g., persian_teampro): ").strip()
            if not ch_name: continue
            config["channels"][ch_name] = configure_channel()
            print(f"\n[+] '{ch_name}' staged for saving.")

        elif choice == '2':
            if not config["channels"]:
                print("No channels configured yet.")
                continue
            print("\nAvailable Channels:")
            for ch in config["channels"]: print(f" - {ch}")
            ch_name = input("Enter channel name to edit: ").strip()
            if ch_name in config["channels"]:
                config["channels"][ch_name] = configure_channel(config["channels"][ch_name])
                print(f"\n[+] '{ch_name}' updated.")
            else:
                print("Channel not found.")

        elif choice == '3':
            ch_name = input("Enter channel name to delete: ").strip()
            if ch_name in config["channels"]:
                del config["channels"][ch_name]
                print(f"\n[-] '{ch_name}' deleted.")
            else:
                print("Channel not found.")

        elif choice == '4':
            print("\nActive Channels:")
            for ch, data in config["channels"].items():
                print(f" - {ch} (Target: {data.get('chat_id')}, Lang: {data.get('language')})")
            print(f"\nGlobal Catch-All Gate: {config.get('catch_all_channel') or 'disabled'}")

        elif choice == '5':
            current_gate = config.get("catch_all_channel") or ""
            print("\n--- Global Catch-All Review Gate ---")
            print("Previews of every post are sent here for review before going live.")
            print("Type 'me' for Saved Messages, an @username or numeric ID, or 'off' to disable.")
            print("Press Enter to keep the current setting.")
            gate = input(f"Enter target [{current_gate or 'disabled'}]: ").strip()
            if gate.lower() == "off":
                config["catch_all_channel"] = ""
                print("[+] Catch-all gate disabled. Previews will not be sent.")
            elif gate:
                config["catch_all_channel"] = gate
                print("[+] Catch-all gate updated.")
            else:
                print("[i] Catch-all gate unchanged.")

        elif choice == '0':
            save_config(config)
            break
        else:
            print("Invalid option.")

if __name__ == "__main__":
    main()
