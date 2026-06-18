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
        # Return bounding box
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
    if not session_dir: return

    config = json.load(open(CONFIG_FILE, "r", encoding="utf-8"))
    raw_path = glob.glob(os.path.join(session_dir, "raw_image.*"))[0]

    # 1. Global AOI selection
    global_aoi = None
    if os.environ.get("DISPLAY") and input("[?] Define manual AOI? (y/n): ").lower() in ['y', 'yes']:
        global_aoi = select_aoi_on_image(raw_path)

    for channel_name, profile in config["channels"].items():
        # Load metadata
        md_path = os.path.join(session_dir, f"{profile['language']}.md")
        headline = extract_markdown_headline(md_path)
        layout = profile["image_layout"]
        placement = layout["raw_image_placement"]

        # 2. Adaptive Viewport Logic
        raw_img = Image.open(raw_path).convert("RGBA")
        target_size = (placement["width"], placement["height"])

        if global_aoi:
            aoi_box = global_aoi # (left, top, right, bottom)
            aoi_area = ((aoi_box[2]-aoi_box[0]) * (aoi_box[3]-aoi_box[1])) / (raw_img.width * raw_img.height)

            if aoi_area > 0.60:
                # FIT/PAD MODE: Respect all AOI contents
                snippet = ImageOps.pad(raw_img.crop(aoi_box), target_size, color=(0,0,0,0))
            else:
                # PAN/COVER MODE: Focus on AOI center
                center_x = (aoi_box[0] + aoi_box[2]) / (2 * raw_img.width)
                center_y = (aoi_box[1] + aoi_box[3]) / (2 * raw_img.height)
                snippet = ImageOps.fit(raw_img, target_size, centering=(center_x, center_y))
        else:
            snippet = ImageOps.fit(raw_img, target_size, centering=(0.5, 0.5))

        # 3. Canvas Composition
        canvas = Image.new("RGBA", (1000, 1000), (0,0,0,0))
        canvas.paste(snippet, (placement["x"], placement["y"]))
        overlay = Image.open(os.path.join(PROJECT_ROOT, layout["template_overlay_path"])).convert("RGBA")
        canvas = Image.alpha_composite(canvas, overlay)

        # 4. Headline Processing with Overflow Check
        # ... [Logic from previous step to render text and handle overflow] ...
        # (Using the loop + choice 1, 2, 3 as defined previously)

        canvas.save(os.path.join(session_dir, f"{channel_name}_broadcast.png"))
        print(f"  [+] Generated: {channel_name}_broadcast.png")

if __name__ == "__main__":
    render_channel_assets()
