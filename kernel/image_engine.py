import os
import glob
import tkinter as tk

# Imported before PIL so the bundled FriBiDi is on PATH when Pillow loads it
from common import (
    PROJECT_ROOT,
    load_channels_config, get_latest_session_directory, input_with_timeout,
    load_gemini_credentials, select_operational_model,
)

from PIL import Image, ImageDraw, ImageFont, ImageTk, ImageOps, ImageFilter, features
import arabic_reshaper
from bidi.algorithm import get_display

# Attempt to load GenAI
try:
    from google import genai
except ImportError:
    genai = None

KURDISH_LANG_CODES = ['ckb', 'ku', 'kurdish']

# Smallest size the overflow menu's auto-shrink option goes down to
MIN_FONT_SIZE = 18

# Raqm (HarfBuzz + FriBiDi) shapes RTL text properly from the raw string.
# Without it we fall back to arabic_reshaper + python-bidi, which cannot
# shape the Kurdish letters ڵ ڕ ێ ە and has to substitute look-alikes.
RAQM_AVAILABLE = features.check("raqm")

def extract_markdown_headline(md_file_path):
    if not os.path.exists(md_file_path): return None
    with open(md_file_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith("#"): return line.lstrip("#").strip()
    return None

def shape_rtl(text, lang_code=None, custom_reshaper=None):
    """Fallback RTL shaping for when Raqm is unavailable.

    arabic_reshaper has no presentation forms for the Kurdish letters ڵ ڕ ێ ە,
    so they are swapped for look-alikes; ڵ ڕ ێ lose their V mark as a result.
    """
    process_line = text
    if lang_code in KURDISH_LANG_CODES:
        # 1. Pre-Reshape Setup
        process_line = process_line.replace('ە', 'ة') # Ae -> Teh Marbuta
        process_line = process_line.replace('ھ', 'ه') # Kurdish Heh -> Arabic Heh
        process_line = process_line.replace('ێ', 'ی').replace('ڕ', 'ر').replace('ڵ', 'ل')

    if custom_reshaper:
        reshaped = custom_reshaper.reshape(process_line)
    else:
        reshaped = arabic_reshaper.reshape(process_line)

    if lang_code in KURDISH_LANG_CODES:
        # 2. Post-Reshape Ligature Busters & Swaps
        reshaped = reshaped.replace('\uFE93', '\uFEE9') # Isolated Teh Marbuta -> Isolated Heh
        reshaped = reshaped.replace('\uFE94', '\uFEEA') # Final Teh Marbuta -> Final Heh
        reshaped = reshaped.replace('\u0629', '\uFEE9') # Raw fallback

    return get_display(reshaped)

def prepare_line(text, is_rtl, lang_code=None, custom_reshaper=None):
    """Returns the text to draw and the extra textlength/text arguments it needs."""
    if not is_rtl:
        return text, {}
    if RAQM_AVAILABLE:
        return text, {"direction": "rtl", "language": lang_code}
    return shape_rtl(text, lang_code, custom_reshaper), {}

def wrap_text(text, font, max_width, draw, is_rtl=False, custom_reshaper=None, lang_code=None):
    """Wraps text intelligently. Uses a custom RTL reshaper if provided."""
    words = text.split()
    lines, current_line = [], []
    for word in words:
        test_line = ' '.join(current_line + [word])
        text_to_measure, layout_args = prepare_line(test_line, is_rtl, lang_code, custom_reshaper)

        if draw.textlength(text_to_measure, font=font, **layout_args) <= max_width:
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

def find_raw_image(session_dir):
    """Returns the path of the session's raw_image.* file, or None."""
    raw_images = glob.glob(os.path.join(session_dir, "raw_image.*"))
    return raw_images[0] if raw_images else None

def headline_style(layout, is_rtl):
    """Reads a channel's headline_safe_area settings, filling in the defaults for missing keys."""
    safe_area = layout.get("headline_safe_area", {})
    return {
        "font_path": os.path.join(PROJECT_ROOT, safe_area.get("font_path", "_config/fonts/Dana-Medium.ttf")),
        "font_size": safe_area.get("font_size", 48),
        "color": safe_area.get("font_color", "#ffffff"),
        "x": safe_area.get("x_start", 36),
        "y": safe_area.get("y_start", 700),
        "width": safe_area.get("width", 930),
        "max_height": safe_area.get("max_height", 195),
        "max_lines": safe_area.get("max_lines", 2),
        "line_spacing": safe_area.get("line_spacing", 1.1),
        "alignment": safe_area.get("alignment", "right" if is_rtl else "left").lower(),
    }

def make_rtl_reshaper(is_rtl):
    """Returns the arabic_reshaper for the fallback shaping, or None when it isn't needed."""
    if not is_rtl or RAQM_AVAILABLE:
        return None
    # FORCE ARABIC MODE TO ENSURE STABLE SHAPING
    reshaper_config = {
        'language': 'Arabic',
        'delete_harakat': False,
        'support_ligatures': True
    }
    return arabic_reshaper.ArabicReshaper(configuration=reshaper_config)

def layout_headline(headline, style, font_size, is_rtl, lang_code, custom_reshaper=None):
    """Wraps the headline at font_size and checks it against the safe area.

    Returns a dict with the font, lines, line_height, total_height and fits.
    """
    try:
        font = ImageFont.truetype(style["font_path"], font_size)
    except IOError:
        print(f"  [FATAL] Could not load font at: {style['font_path']}")
        font = ImageFont.load_default()

    measure_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lines = wrap_text(headline, font, style["width"], measure_draw, is_rtl, custom_reshaper, lang_code)
    line_height = font_size * style["line_spacing"]
    total_height = len(lines) * line_height
    fits = total_height <= style["max_height"] and len(lines) <= style["max_lines"]
    return {"font": font, "lines": lines, "line_height": line_height, "total_height": total_height, "fits": fits}

def shrink_font_size(headline, style, font_size, is_rtl, lang_code, custom_reshaper=None):
    """Lowers the font size 2 px at a time until the headline fits, stopping at MIN_FONT_SIZE."""
    while font_size > MIN_FONT_SIZE:
        font_size -= 2
        if layout_headline(headline, style, font_size, is_rtl, lang_code, custom_reshaper)["fits"]:
            break
    return font_size

def compose_image(raw_path, layout, aoi=None, blur_radius=30):
    """Places the photo on a blurred copy of itself and overlays the channel template.

    aoi is (left, top, right, bottom) in photo pixels and may extend past the photo's edges.
    """
    placement = layout["raw_image_placement"]

    raw_img = Image.open(raw_path).convert("RGBA")
    target_size = (placement["width"], placement["height"])
    target_w, target_h = target_size

    if aoi:
        min_x = min(0, aoi[0])
        min_y = min(0, aoi[1])
        max_x = max(raw_img.width, aoi[2])
        max_y = max(raw_img.height, aoi[3])

        if min_x < 0 or min_y < 0 or max_x > raw_img.width or max_y > raw_img.height:
            raw_img = raw_img.crop((min_x, min_y, max_x, max_y))
            adjusted_aoi = (
                aoi[0] - min_x, aoi[1] - min_y,
                aoi[2] - min_x, aoi[3] - min_y
            )
        else:
            adjusted_aoi = aoi

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
    canvas = blurred_bg.filter(ImageFilter.GaussianBlur(radius=blur_radius))

    canvas.paste(snippet, (placement["x"], placement["y"]), snippet)

    template_relative_path = layout.get("template_overlay_path")
    overlay = Image.open(os.path.join(PROJECT_ROOT, template_relative_path)).convert("RGBA")
    return Image.alpha_composite(canvas, overlay)

def draw_headline(canvas, headline_layout, style, is_rtl, lang_code, custom_reshaper=None):
    """Draws the wrapped headline lines, centered vertically in the safe area."""
    draw = ImageDraw.Draw(canvas)
    font = headline_layout["font"]
    max_w = style["width"]

    y_offset = max(0, (style["max_height"] - headline_layout["total_height"]) / 2)
    current_y = style["y"] + y_offset

    for line in headline_layout["lines"]:
        text_to_draw, layout_args = prepare_line(line, is_rtl, lang_code, custom_reshaper)

        line_w = draw.textlength(text_to_draw, font=font, **layout_args)
        if style["alignment"] == "center":
            line_start_x = style["x"] + ((max_w - line_w) / 2)
        elif style["alignment"] == "right":
            line_start_x = style["x"] + max_w - line_w
        else:
            line_start_x = style["x"]

        draw.text((line_start_x, current_y), text_to_draw, font=font, fill=style["color"], **layout_args)
        current_y += headline_layout["line_height"]

def render_channel(session_dir, channel_name, profile, raw_path, aoi=None, blur_radius=30, headline=None, font_size=None):
    """Renders <channel>_broadcast.jpg without asking anything.

    headline defaults to the first line of <lang>.md, font_size to the channel's font_size.
    The image is written even when the headline overflows, so the result can be inspected.
    Returns {"path", "headline", "font_size", "fits"}.
    """
    lang_code = profile.get("language", "en").lower()
    is_rtl = profile.get("is_rtl", False)
    layout = profile["image_layout"]
    style = headline_style(layout, is_rtl)
    custom_reshaper = make_rtl_reshaper(is_rtl)

    if headline is None:
        headline = extract_markdown_headline(os.path.join(session_dir, f"{lang_code}.md"))
    font_size = font_size or style["font_size"]

    canvas = compose_image(raw_path, layout, aoi, blur_radius)

    fits = True
    if headline:
        headline_layout = layout_headline(headline, style, font_size, is_rtl, lang_code, custom_reshaper)
        draw_headline(canvas, headline_layout, style, is_rtl, lang_code, custom_reshaper)
        fits = headline_layout["fits"]

    final_hd_image = canvas.convert("RGB")
    out_path = os.path.join(session_dir, f"{channel_name}_broadcast.jpg")
    final_hd_image.save(out_path, "JPEG", quality=100, subsampling=0)

    print(f"  [+] Generated: {channel_name}_broadcast.jpg")
    return {"path": out_path, "headline": headline, "font_size": font_size, "fits": fits}

def ask_until_headline_fits(session_dir, channel_name, profile):
    """Shows the overflow menu in the terminal until the channel's headline fits.

    Returns the headline and font size to render with.
    """
    lang_code = profile.get("language", "en").lower()
    is_rtl = profile.get("is_rtl", False)
    style = headline_style(profile["image_layout"], is_rtl)
    custom_reshaper = make_rtl_reshaper(is_rtl)

    headline = extract_markdown_headline(os.path.join(session_dir, f"{lang_code}.md"))
    font_size = style["font_size"]

    while headline:
        if layout_headline(headline, style, font_size, is_rtl, lang_code, custom_reshaper)["fits"]:
            break

        print(f"\n[!] OVERFLOW ALERT for {channel_name} ({lang_code})")
        print(f"    Current headline text breaches the defined safe area boundaries.")
        print(f"    Text: {headline}")
        print("    1. Auto-shrink font size to fit")
        print("    2. Ask Gemini to rewrite/shorten the headline")
        print("    3. Type a manual override")

        choice = input_with_timeout("Select an option (1/2/3)", "2").strip()

        if choice == "1":
            font_size = shrink_font_size(headline, style, font_size, is_rtl, lang_code, custom_reshaper)
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
                print(f"    [+] Gemini proposed: {headline}")
            except Exception as e:
                print(f"\n    [X] SERVER ERROR: Google's API rejected the request.")
                print(f"        {str(e).split('.')[0]}.")
                print("    [!] The selected model is likely overloaded. Please try again or select a different model.")

            font_size = style["font_size"]

        elif choice == "3":
            headline = input("    [?] Enter shorter headline: ").strip()
            font_size = style["font_size"]

    return headline, font_size

def render_channel_assets(session_dir=None):
    """Renders every channel's image, asking for the AOI, blur and overflow fixes in the terminal."""
    session_dir = session_dir or get_latest_session_directory()
    if not session_dir:
        print("[ERROR] No session directory found inside _workspace.")
        return

    config = load_channels_config()
    raw_path = find_raw_image(session_dir)
    if not raw_path:
        print(f"[ERROR] Could not find any raw_image.* inside {session_dir}")
        return

    global_aoi = None
    aoi_choice = input_with_timeout("[?] Define manual AOI? (y/n)", "n")
    if aoi_choice.lower() in ['y', 'yes']:
        global_aoi = select_aoi_on_image(raw_path)

    if not RAQM_AVAILABLE:
        print("[!] Raqm text layout is unavailable (FriBiDi library not found).")
        print("    Falling back to arabic_reshaper: Kurdish letters ڵ ڕ ێ will render without their V mark.")

    blur_input = input_with_timeout("[?] Enter background blur radius", "30").strip()
    try:
        blur_radius = int(blur_input) if blur_input else 30
    except ValueError:
        print("  [!] Invalid input. Defaulting to 30.")
        blur_radius = 30

    for channel_name, profile in config["channels"].items():
        headline, font_size = ask_until_headline_fits(session_dir, channel_name, profile)
        render_channel(session_dir, channel_name, profile, raw_path, global_aoi, blur_radius, headline, font_size)

if __name__ == "__main__":
    render_channel_assets()
