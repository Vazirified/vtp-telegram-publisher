import os
import glob
import json
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

# 1. Absolute Path Setup
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
CONFIG_FILE = os.path.join(PROJECT_ROOT, "_config", "channels.json")
WORKSPACE_DIR = os.path.join(PROJECT_ROOT, "_workspace")

def load_config():
    """Loads the channel registry configuration."""
    if not os.path.exists(CONFIG_FILE):
        print(f"[ERROR] Configuration file missing: {CONFIG_FILE}")
        return {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def get_latest_session_directory():
    """Automatically finds the most recent workspace session folder."""
    sessions = glob.glob(os.path.join(WORKSPACE_DIR, "session_*"))
    if not sessions:
        return None
    # Sort folders by timestamp name and pick the newest one
    return sorted(sessions)[-1]

def extract_markdown_headline(md_file_path):
    """Scans a Markdown file and extracts the first headline string."""
    if not os.path.exists(md_file_path):
        return None
    with open(md_file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("#"):
                # Strip the markdown hash and any surrounding whitespace
                return line.lstrip("#").strip()
            elif line: # Fallback if no '#' is used, take first text line
                return line
    return None

def wrap_text(text, font, max_width, draw):
    """Breaks a long string into multiple lines that fit within max_width."""
    words = text.split()
    lines = []
    current_line = []

    for word in words:
        test_line = ' '.join(current_line + [word])
        # Pillow >= 10.0 uses textlength for width calculation
        w = draw.textlength(test_line, font=font)

        if w <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(' '.join(current_line))
                current_line = [word]
            else:
                # Edge case: A single word is longer than the max width
                lines.append(word)
                current_line = []

    if current_line:
        lines.append(' '.join(current_line))

    return lines

def render_channel_assets(session_dir=None):
    """Main image generation loop based on channel definitions."""
    if not session_dir:
        session_dir = get_latest_session_directory()

    if not session_dir or not os.path.exists(session_dir):
        print("[ERROR] No valid workspace session found to process.")
        return

    print(f"\n[~] Initializing Image Engine for session: {os.path.basename(session_dir)}")
    config = load_config()
    channels = config.get("channels", {})

    if not channels:
        print("[!] No channels registered in configuration. Halting.")
        return

    for channel_name, profile in channels.items():
        lang_code = profile.get("language", "en")
        md_path = os.path.join(session_dir, f"{lang_code}.md")

        if not os.path.exists(md_path):
            print(f"  [SKIP] {channel_name}: Required translation '{lang_code}.md' not found.")
            continue

        headline = extract_markdown_headline(md_path)
        if not headline:
            print(f"  [SKIP] {channel_name}: Could not extract headline from {lang_code}.md.")
            continue

        # 1. Prepare RTL text (Reshape first, we apply BiDi AFTER wrapping to preserve line order)
        is_rtl = profile.get("is_rtl", False)
        if is_rtl:
            headline = arabic_reshaper.reshape(headline)

        # 2. Extract Layout Metrics
        layout = profile.get("image_layout", {})
        template_path = os.path.join(PROJECT_ROOT, layout.get("template_overlay_path", ""))
        safe_area = layout.get("headline_safe_area", {})

        if not os.path.exists(template_path):
            print(f"  [ERROR] {channel_name}: Template graphic missing at {template_path}")
            continue

        # 3. Load Base Image and Font
        try:
            img = Image.open(template_path).convert("RGBA")
            draw = ImageDraw.Draw(img)

            font_path = os.path.join(PROJECT_ROOT, safe_area.get("font_path", ""))
            font_size = safe_area.get("font_size", 44)
            font_color = safe_area.get("font_color", "#FFFFFF")

            try:
                font = ImageFont.truetype(font_path, font_size)
            except IOError:
                print(f"  [WARN] {channel_name}: Font missing ({font_path}). Using default.")
                font = ImageFont.load_default()

        except Exception as e:
            print(f"  [ERROR] {channel_name}: Failed to load image assets - {e}")
            continue

        # 4. Text Wrapping
        max_width = safe_area.get("width", 800)
        lines = wrap_text(headline, font, max_width, draw)

        # 5. DYNAMIC VERTICAL CENTERING MATH
        # Calculate standard height of one line of text for this font
        bbox = font.getbbox("Agyپچ") # Mixed tall/descending characters for safe height
        line_height = bbox[3] - bbox[1]
        line_spacing = 10 # Extra padding between wrapped lines

        total_text_block_height = (len(lines) * line_height) + ((len(lines) - 1) * line_spacing)

        box_y_start = safe_area.get("y_start", 100)
        box_max_height = safe_area.get("max_height", 300)

        # Suspend the text block perfectly in the middle of the defined bounding box height
        y_offset = box_y_start + ((box_max_height - total_text_block_height) / 2)

        # 6. Render Text Line by Line
        box_x_start = safe_area.get("x_start", 100)
        alignment = safe_area.get("alignment", "center")

        for line in lines:
            # If RTL, apply BiDi flip to the individual line so it reads correctly right-to-left
            display_line = get_display(line) if is_rtl else line

            line_width = draw.textlength(display_line, font=font)

            # Horizontal Justification Math
            if alignment == "center":
                x = box_x_start + ((max_width - line_width) / 2)
            elif alignment == "right":
                x = box_x_start + max_width - line_width
            else: # left
                x = box_x_start

            draw.text((x, y_offset), display_line, font=font, fill=font_color)
            y_offset += (line_height + line_spacing)

        # 7. Save the Channel Broadcast Asset
        output_filename = f"{channel_name}_broadcast.png"
        output_path = os.path.join(session_dir, output_filename)
        img.save(output_path, "PNG")
        print(f"  [+] Generated: {output_filename}")

    print("\n[SUCCESS] Graphic Engine processing complete.")

if __name__ == "__main__":
    # If run directly, it automatically grabs the latest folder in _workspace/
    render_channel_assets()
