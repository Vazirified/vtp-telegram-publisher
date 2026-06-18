import os
import glob
import json
import tkinter as tk
from PIL import Image, ImageDraw, ImageFont, ImageTk, ImageOps
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

def get_latest_session_directory():
    sessions = glob.glob(os.path.join(WORKSPACE_DIR, "session_*"))
    return sorted(sessions)[-1] if sessions else None

def extract_markdown_headline(md_file_path):
    if not os.path.exists(md_file_path): return None
    with open(md_file_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith("#"): return line.lstrip("#").strip()
    return None

def wrap_text(text, font, max_width, draw):
    words = text.split()
    lines, current_line = [], []
    for word in words:
        test_line = ' '.join(current_line + [word])
        if draw.textlength(test_line, font=font) <= max_width:
            current_line.append(word)
        else:
            lines.append(' '.join(current_line))
            current_line = [word]
    if current_line: lines.append(' '.join(current_line))
    return lines

def select_aoi_on_image(image_path):
    root = tk.Tk()
    root.title("Define Area of Interest (2 clicks: Top-Left, Bottom-Right)")
    img = Image.open(image_path)
    preview = img.copy()
    preview.thumbnail((800, 600))
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
        scale_x = img.width / preview.width
        scale_y = img.height / preview.height
        p1 = (int(points[0][0] * scale_x), int(points[0][1] * scale_y))
        p2 = (int(points[1][0] * scale_x), int(points[1][1] * scale_y))
        return (min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1]))
    return None

def shorten_headline_with_gemini(headline, lang_code):
    if not genai or not os.environ.get("GEMINI_API_KEY"): return None
    client = genai.Client()
    prompt = f"Shorten this headline for a broadcast graphic, keep language {lang_code}: {headline}"
    response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
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

    # 1. Global AOI selection
    global_aoi = None
    if input("[?] Define manual AOI? (y/n): ").lower() in ['y', 'yes']:
        global_aoi = select_aoi_on_image(raw_path)

    for channel_name, profile in config["channels"].items():
        md_path = os.path.join(session_dir, f"{profile['language']}.md")
        headline = extract_markdown_headline(md_path)
        layout = profile["image_layout"]
        placement = layout["raw_image_placement"]

        # 2. Adaptive Viewport Logic
        raw_img = Image.open(raw_path).convert("RGBA")
        target_size = (placement["width"], placement["height"])

        if global_aoi:
            aoi_box = global_aoi
            aoi_area = ((aoi_box[2]-aoi_box[0]) * (aoi_box[3]-aoi_box[1])) / (raw_img.width * raw_img.height)

            if aoi_area > 0.60:
                snippet = ImageOps.pad(raw_img.crop(aoi_box), target_size, color=(0,0,0,0))
            else:
                center_x = (aoi_box[0] + aoi_box[2]) / (2 * raw_img.width)
                center_y = (aoi_box[1] + aoi_box[3]) / (2 * raw_img.height)
                snippet = ImageOps.fit(raw_img, target_size, centering=(center_x, center_y))
        else:
            snippet = ImageOps.fit(raw_img, target_size, centering=(0.5, 0.5))

        # 3. Canvas Composition
        canvas = Image.new("RGBA", (1000, 1000), (0,0,0,0))
        canvas.paste(snippet, (placement["x"], placement["y"]))

        template_relative_path = layout.get("template_overlay_path")
        overlay = Image.open(os.path.join(PROJECT_ROOT, template_relative_path)).convert("RGBA")
        canvas = Image.alpha_composite(canvas, overlay)

        # 4. Headline Processing with Execution Loop
        if headline:
            safe_area = layout.get("headline_safe_area", {})

            # Map the exact keys from the JSON configuration
            font_path_relative = safe_area.get("font_path", "_config/fonts/Dana-Medium.ttf")
            font_path = os.path.join(PROJECT_ROOT, font_path_relative)

            font_size = safe_area.get("font_size", 48)
            color = safe_area.get("font_color", "#ffffff")

            render_x = safe_area.get("x_start", 36)
            render_y = safe_area.get("y_start", 700)
            max_w = safe_area.get("width", 930)
            max_h = safe_area.get("max_height", 195)
            max_lines = safe_area.get("max_lines", 2)

            line_spacing = safe_area.get("line_spacing", 1.1)

            is_rtl = profile.get("is_rtl", False)
            alignment = safe_area.get("alignment", "right" if is_rtl else "left").lower()

            draw = ImageDraw.Draw(canvas)

            # Auto-shrink font sizing block if text boundaries overflow
            while font_size > 18:
                try:
                    font = ImageFont.truetype(font_path, font_size)
                except IOError:
                    print(f"  [FATAL] Could not load font at: {font_path}")
                    font = ImageFont.load_default()
                    lines = wrap_text(headline, font, max_w, draw)
                    total_height = 0
                    break

                lines = wrap_text(headline, font, max_w, draw)

                # Dynamic height boundaries using true font typography metrics
                ascent, descent = font.getmetrics()
                true_font_height = ascent + descent
                line_height = true_font_height * line_spacing
                total_height = len(lines) * line_height

                if total_height <= max_h and len(lines) <= max_lines:
                    break
                font_size -= 2

            # Choice 2/3 Fallback: Try Gemini if font shrinking fails
            if (len(lines) > max_lines or total_height > max_h) and genai and os.environ.get("GEMINI_API_KEY"):
                print(f"  [~] Text overflow for {channel_name}. Shortening via Gemini AI...")
                short_headline = shorten_headline_with_gemini(headline, profile["language"])
                if short_headline:
                    headline = short_headline
                    font_size = safe_area.get("font_size", 48)
                    font = ImageFont.truetype(font_path, font_size)
                    lines = wrap_text(headline, font, max_w, draw)

                    ascent, descent = font.getmetrics()
                    true_font_height = ascent + descent
                    line_height = true_font_height * line_spacing
                    total_height = len(lines) * line_height

            # --- CALCULATE VERTICAL CENTERING ---
            y_offset = max(0, (max_h - total_height) / 2)
            current_y = render_y + y_offset

            # Draw rendering loops
            for line in lines:
                text_to_draw = line

                # Apply script reshaping if RTL
                if is_rtl:
                    reshaped = arabic_reshaper.reshape(line)
                    text_to_draw = get_display(reshaped)

                # Calculate the exact pixel width of the current line
                line_w = draw.textlength(text_to_draw, font=font)

                # --- APPLY HORIZONTAL ALIGNMENT ---
                if alignment == "center":
                    line_start_x = render_x + ((max_w - line_w) / 2)
                elif alignment == "right":
                    line_start_x = render_x + max_w - line_w
                else:  # left alignment
                    line_start_x = render_x

                # Draw the line and advance the Y coordinate
                draw.text((line_start_x, current_y), text_to_draw, font=font, fill=color)
                current_y += line_height

        canvas.save(os.path.join(session_dir, f"{channel_name}_broadcast.png"))
        print(f"  [+] Generated: {channel_name}_broadcast.png")

if __name__ == "__main__":
    render_channel_assets()
