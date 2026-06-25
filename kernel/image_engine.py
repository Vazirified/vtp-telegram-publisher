import os
import glob
import json
import tkinter as tk
from PIL import Image, ImageDraw, ImageFont, ImageTk, ImageOps, ImageFilter
import arabic_reshaper
from bidi.algorithm import get_display

# Attempt to load GenAI
try:
    from google import genai
except ImportError:
    genai = None

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
CONFIG_FILE = os.path.join(PROJECT_ROOT, "_config", "channels.json")
WORKSPACE_DIR = os.path.join(PROJECT_ROOT, "_workspace")
CREDENTIALS_DIR = os.path.join(PROJECT_ROOT, "_credentials")
GEMINI_KEYS_FILE = os.path.join(CREDENTIALS_DIR, "gemini_keys.json")

def load_gemini_credentials():
    if os.path.exists(GEMINI_KEYS_FILE):
        try:
            with open(GEMINI_KEYS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"gemini_api_key": None, "last_used_model": "gemini-1.5-flash"}

def save_gemini_credentials(api_key, model_name):
    if not os.path.exists(CREDENTIALS_DIR):
        os.makedirs(CREDENTIALS_DIR)
    payload = {"gemini_api_key": api_key, "last_used_model": model_name}
    with open(GEMINI_KEYS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

def select_operational_model(cached_profile):
    last_model = cached_profile.get("last_used_model", "gemini-1.5-flash")
    api_token = cached_profile.get("gemini_api_key")

    if not api_token: return last_model

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
        print(f"  [{index}] {name.replace('-', ' ').title()} ({name})")
    print(f"  [Enter] Reuse Last Verified Default ({last_model})")
    print("========================================================")

    choice = input("[?] Select engine target lane: ").strip()
    selected_model = model_matrix.get(choice, last_model)
    save_gemini_credentials(api_token, selected_model)
    return selected_model

def get_latest_session_directory():
    sessions = glob.glob(os.path.join(WORKSPACE_DIR, "session_*"))
    return sorted(sessions)[-1] if sessions else None

def extract_markdown_headline(md_file_path):
    if not os.path.exists(md_file_path): return None
    with open(md_file_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith("#"): return line.lstrip("#").strip()
    return None

def wrap_text(text, font, max_width, draw, is_rtl=False, custom_reshaper=None, lang_code=None):
    """Wraps text intelligently. Uses a custom RTL reshaper if provided."""
    words = text.split()
    lines, current_line = [], []
    for word in words:
        test_line = ' '.join(current_line + [word])
        text_to_measure = test_line
        if is_rtl:
            if custom_reshaper:
                reshaped = custom_reshaper.reshape(test_line)
            else:
                reshaped = arabic_reshaper.reshape(test_line)

            if lang_code in ['ckb', 'ku', 'kurdish']:
                reshaped = reshaped.replace('\uFE93', '\uFEE9').replace('\uFE94', '\uFEEA')

            text_to_measure = get_display(reshaped)

        if draw.textlength(text_to_measure, font=font) <= max_width:
            current_line.append(word)
        else:
            lines.append(' '.join(current_line))
            current_line = [word]
    if current_line: lines.append(' '.join(current_line))
    return lines

def select_aoi_on_image(image_path):
    root = tk.Tk()
    root.title("Define AOI (Dark grey is extendable margin for padding)")
    img = Image.open(image_path).convert("RGBA")
    w, h = img.size

    pad_w, pad_h = int(w * 2), int(h * 2)
    offset_x, offset_y = int(w * 0.5), int(h * 0.5)

    padded_img = Image.new("RGBA", (pad_w, pad_h), (40, 40, 40, 255))

    draw_pad = ImageDraw.Draw(padded_img)
    grid_spacing = max(50, int(w * 0.1))
    grid_color = (90, 90, 90, 255)
    line_thickness = max(2, int(pad_w / 1000))

    for x in range(offset_x % grid_spacing, pad_w, grid_spacing):
        draw_pad.line([(x, 0), (x, pad_h)], fill=grid_color, width=line_thickness)

    for y in range(offset_y % grid_spacing, pad_h, grid_spacing):
        draw_pad.line([(0, y), (pad_w, y)], fill=grid_color, width=line_thickness)

    padded_img.paste(img, (offset_x, offset_y))

    preview = padded_img.copy()
    preview.thumbnail((1000, 800))
    photo = ImageTk.PhotoImage(preview)

    label = tk.Label(root, image=photo)
    label.pack()

    points = []
    def on_click(event):
        points.append((event.x, event.y))
        if len(points) == 2:
            root.quit(); root.destroy()

    label.bind("<Button-1>", on_click)
    root.mainloop()

    if len(points) == 2:
        scale_x = pad_w / preview.width
        scale_y = pad_h / preview.height

        p1_pad = (points[0][0] * scale_x, points[0][1] * scale_y)
        p2_pad = (points[1][0] * scale_x, points[1][1] * scale_y)

        p1 = (int(p1_pad[0] - offset_x), int(p1_pad[1] - offset_y))
        p2 = (int(p2_pad[0] - offset_x), int(p2_pad[1] - offset_y))

        return (min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1]))
    return None

def shorten_headline_with_gemini(headline, lang_code, api_token, active_model):
    client = genai.Client(api_key=api_token)
    prompt = f"Shorten this headline for a broadcast graphic so it fits perfectly on a screen. Keep the original language ({lang_code}). Output ONLY the shortened headline without quotes: {headline}"
    response = client.models.generate_content(model=active_model, contents=prompt)
    return response.text.strip().strip('"\'')

def render_channel_assets(session_dir=None):
    session_dir = session_dir or get_latest_session_directory()
    if not session_dir:
        print("[ERROR] No session directory found inside _workspace.")
        return

    config = json.load(open(CONFIG_FILE, "r", encoding="utf-8"))
    raw_images = glob.glob(os.path.join(session_dir, "raw_image.*"))
    if not raw_images:
        print(f"[ERROR] Could not find any raw_image.* inside {session_dir}")
        return
    raw_path = raw_images[0]

    global_aoi = None
    if input("[?] Define manual AOI? (y/n): ").lower() in ['y', 'yes']:
        global_aoi = select_aoi_on_image(raw_path)

    for channel_name, profile in config["channels"].items():
        lang_code = profile.get("language", "en").lower()
        is_rtl = profile.get("is_rtl", False)

        md_path = os.path.join(session_dir, f"{lang_code}.md")
        headline = extract_markdown_headline(md_path)

        if headline and lang_code in ['ckb', 'ku', 'kurdish']:
            headline = headline.replace('ە', 'ة')
            headline = headline.replace('ێ', 'ی').replace('ڕ', 'ر').replace('ڵ', 'ل')

        layout = profile["image_layout"]
        placement = layout["raw_image_placement"]

        custom_reshaper = None
        if is_rtl:
            reshaper_lang = 'Arabic'
            if lang_code in ['ckb', 'ku', 'kurdish']:
                reshaper_lang = 'Kurdish'
            elif lang_code in ['fa', 'per', 'farsi']:
                reshaper_lang = 'Farsi'
            elif lang_code in ['ur', 'urdu']:
                reshaper_lang = 'Urdu'

            reshaper_config = {
                'language': reshaper_lang,
                'delete_harakat': False,
                'support_ligatures': True
            }
            custom_reshaper = arabic_reshaper.ArabicReshaper(configuration=reshaper_config)

        raw_img = Image.open(raw_path).convert("RGBA")
        target_size = (placement["width"], placement["height"])
        target_w, target_h = target_size

        if global_aoi:
            min_x = min(0, global_aoi[0])
            min_y = min(0, global_aoi[1])
            max_x = max(raw_img.width, global_aoi[2])
            max_y = max(raw_img.height, global_aoi[3])

            if min_x < 0 or min_y < 0 or max_x > raw_img.width or max_y > raw_img.height:
                raw_img = raw_img.crop((min_x, min_y, max_x, max_y))
                adjusted_aoi = (
                    global_aoi[0] - min_x, global_aoi[1] - min_y,
                    global_aoi[2] - min_x, global_aoi[3] - min_y
                )
            else:
                adjusted_aoi = global_aoi

            aoi_w = adjusted_aoi[2] - adjusted_aoi[0]
            aoi_h = adjusted_aoi[3] - adjusted_aoi[1]
            aoi_area_ratio = (aoi_w * aoi_h) / (raw_img.width * raw_img.height)

            if aoi_area_ratio > 0.60:
                cropped_aoi = raw_img.crop(adjusted_aoi)
                snippet = ImageOps.pad(cropped_aoi, target_size, color=(0,0,0,0))
            else:
                scale = max(target_w / raw_img.width, target_h / raw_img.height)
                new_w, new_h = int(raw_img.width * scale), int(raw_img.height * scale)
                resized_img = raw_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

                aoi_center_x = ((adjusted_aoi[0] + adjusted_aoi[2]) / 2) * scale
                aoi_center_y = ((adjusted_aoi[1] + adjusted_aoi[3]) / 2) * scale

                ideal_x, ideal_y = aoi_center_x - (target_w / 2), aoi_center_y - (target_h / 2)
                crop_x = max(0, min(ideal_x, new_w - target_w))
                crop_y = max(0, min(ideal_y, new_h - target_h))

                snippet = resized_img.crop((crop_x, crop_y, crop_x + target_w, crop_y + target_h))
        else:
            snippet = ImageOps.fit(raw_img, target_size, centering=(0.5, 0.5))

        canvas_w, canvas_h = layout.get("canvas_size", [1000, 1000])

        bg_source = Image.open(raw_path).convert("RGBA")
        blurred_bg = ImageOps.fit(bg_source, (canvas_w, canvas_h), centering=(0.5, 0.5))
        canvas = blurred_bg.filter(ImageFilter.GaussianBlur(radius=30))

        canvas.paste(snippet, (placement["x"], placement["y"]), snippet)

        template_relative_path = layout.get("template_overlay_path")
        overlay = Image.open(os.path.join(PROJECT_ROOT, template_relative_path)).convert("RGBA")
        canvas = Image.alpha_composite(canvas, overlay)

        if headline:
            safe_area = layout.get("headline_safe_area", {})
            font_path = os.path.join(PROJECT_ROOT, safe_area.get("font_path", "_config/fonts/Dana-Medium.ttf"))
            base_font_size = safe_area.get("font_size", 48)
            color = safe_area.get("font_color", "#ffffff")
            render_x = safe_area.get("x_start", 36)
            render_y = safe_area.get("y_start", 700)
            max_w = safe_area.get("width", 930)
            max_h = safe_area.get("max_height", 195)
            max_lines = safe_area.get("max_lines", 2)
            line_spacing = safe_area.get("line_spacing", 1.1)
            alignment = safe_area.get("alignment", "right" if is_rtl else "left").lower()

            draw = ImageDraw.Draw(canvas)
            font_size = base_font_size

            while True:
                try:
                    font = ImageFont.truetype(font_path, font_size)
                except IOError:
                    print(f"  [FATAL] Could not load font at: {font_path}")
                    font = ImageFont.load_default()

                lines = wrap_text(headline, font, max_w, draw, is_rtl, custom_reshaper, lang_code)
                line_height = font_size * line_spacing
                total_height = len(lines) * line_height

                if total_height <= max_h and len(lines) <= max_lines:
                    break

                print(f"\n[!] OVERFLOW ALERT for {channel_name} ({lang_code})")
                print(f"    Current headline text breaches the defined safe area boundaries.")
                print(f"    Text: {headline}")
                print("    1. Auto-shrink font size to fit")
                print("    2. Ask Gemini to rewrite/shorten the headline")
                print("    3. Type a manual override")

                choice = input("Select an option (1/2/3): ").strip()

                if choice == "1":
                    while font_size > 18:
                        font_size -= 2
                        font = ImageFont.truetype(font_path, font_size)
                        lines = wrap_text(headline, font, max_w, draw, is_rtl, custom_reshaper, lang_code)
                        line_height = font_size * line_spacing
                        total_height = len(lines) * line_height
                        if total_height <= max_h and len(lines) <= max_lines:
                            break
                    break

                elif choice == "2":
                    if not genai:
                        print("    [X] Gemini SDK missing. Choose another option.")
                        continue
                    cached_profile = load_gemini_credentials()
                    if not cached_profile.get("gemini_api_key"):
                        print("    [X] Gemini API key missing. Choose another option.")
                        continue

                    active_model = select_operational_model(cached_profile)
                    print(f"    [~] Asking Gemini to shorten...")

                    try:
                        headline = shorten_headline_with_gemini(headline, lang_code, cached_profile.get("gemini_api_key"), active_model)
                        if lang_code in ['ckb', 'ku', 'kurdish']:
                            headline = headline.replace('ە', 'ة')
                            headline = headline.replace('ێ', 'ی').replace('ڕ', 'ر').replace('ڵ', 'ل')
                        print(f"    [+] Gemini proposed: {headline}")
                    except Exception as e:
                        print(f"\n    [X] SERVER ERROR: Google's API rejected the request.")
                        print(f"        {str(e).split('.')[0]}.")
                        print("    [!] The selected model is likely overloaded. Please try again or select a different model.")

                    font_size = base_font_size

                elif choice == "3":
                    headline = input("    [?] Enter shorter headline: ").strip()
                    if lang_code in ['ckb', 'ku', 'kurdish']:
                        headline = headline.replace('ە', 'ة')
                        headline = headline.replace('ێ', 'ی').replace('ڕ', 'ر').replace('ڵ', 'ل')
                    font_size = base_font_size

            y_offset = max(0, (max_h - total_height) / 2)
            current_y = render_y + y_offset

            for line in lines:
                text_to_draw = line
                if is_rtl:
                    if custom_reshaper:
                        reshaped = custom_reshaper.reshape(line)
                    else:
                        reshaped = arabic_reshaper.reshape(line)

                    if lang_code in ['ckb', 'ku', 'kurdish']:
                        reshaped = reshaped.replace('\uFE93', '\uFEE9').replace('\uFE94', '\uFEEA')

                    text_to_draw = get_display(reshaped)

                line_w = draw.textlength(text_to_draw, font=font)
                if alignment == "center":
                    line_start_x = render_x + ((max_w - line_w) / 2)
                elif alignment == "right":
                    line_start_x = render_x + max_w - line_w
                else:
                    line_start_x = render_x

                draw.text((line_start_x, current_y), text_to_draw, font=font, fill=color)
                current_y += line_height

        # --- HD EXPORT LOGIC ---
        # 1. Flatten the RGBA transparency to standard RGB
        final_hd_image = canvas.convert("RGB")
        # 2. Save as maximum quality JPEG with zero chroma subsampling
        out_path = os.path.join(session_dir, f"{channel_name}_broadcast.jpg")
        final_hd_image.save(out_path, "JPEG", quality=100, subsampling=0)

        print(f"  [+] Generated: {channel_name}_broadcast.jpg")

if __name__ == "__main__":
    render_channel_assets()
