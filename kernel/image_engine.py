import os
import glob
import json
import tkinter as tk
from PIL import Image, ImageDraw, ImageFont, ImageTk, ImageOps
import arabic_reshaper
from bidi.algorithm import get_display

# Attempt to bring in the GenAI SDK installed via setup.bat
try:
    from google import genai
except ImportError:
    genai = None

# Absolute Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
CONFIG_FILE = os.path.join(PROJECT_ROOT, "_config", "channels.json")
WORKSPACE_DIR = os.path.join(PROJECT_ROOT, "_workspace")

def get_latest_session_directory():
    """Finds the most recent workspace session folder."""
    sessions = glob.glob(os.path.join(WORKSPACE_DIR, "session_*"))
    return sorted(sessions)[-1] if sessions else None

def extract_markdown_headline(md_file_path):
    """Scans a Markdown translation file and extracts the primary headline."""
    if not os.path.exists(md_file_path):
        return None
    with open(md_file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("#"):
                return line.lstrip("#").strip()
            elif line:
                return line
    return None

def wrap_text(text, font, max_width, draw):
    """Breaks text strings cleanly into wrapped lines matching boundary constraints."""
    words = text.split()
    lines = []
    current_line = []

    for word in words:
        test_line = ' '.join(current_line + [word])
        w = draw.textlength(test_line, font=font)
        if w <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(' '.join(current_line))
                current_line = [word]
            else:
                lines.append(word)
                current_line = []
    if current_line:
        lines.append(' '.join(current_line))
    return lines

def select_aoi_on_image(image_path):
    """Opens a one-time Tkinter modal to capture a global Area of Interest (AOI)."""
    root = tk.Tk()
    root.title("Define Area of Interest (Click Top-Left, then Bottom-Right)")

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
            root.quit()
            root.destroy()

    label.bind("<Button-1>", on_click)
    root.mainloop()

    if len(points) == 2:
        scale_x = img.width / preview.width
        scale_y = img.height / preview.height
        p1 = (int(points[0][0] * scale_x), int(points[0][1] * scale_y))
        p2 = (int(points[1][0] * scale_x), int(points[1][1] * scale_y))
        return (
            (min(p1[0], p2[0]) / img.width, min(p1[1], p2[1]) / img.height),
            (max(p1[0], p2[0]) / img.width, max(p1[1], p2[1]) / img.height)
        )
    return None

def shorten_headline_with_gemini(headline, lang_code):
    """Leverages the Gemini SDK to distill a long headline down intelligently."""
    if not genai:
        print("[!] google-genai library missing. Cannot use AI optimization.")
        return None
    if not os.environ.get("GEMINI_API_KEY"):
        print("[!] GEMINI_API_KEY environment variable is not set.")
        return None

    print("[~] Consulting Gemini Core Engine for architectural truncation...")
    try:
        client = genai.Client()
        prompt = (
            f"You are an expert news editor. Shorten the following headline so it fits perfectly on a compact "
            f"broadcast graphic overlay. The output MUST remain completely in the original language (ISO: {lang_code}). "
            f"Keep it impactful, punchy, and retain the core financial/news truth. Do not include quotes or markdown.\n"
            f"Headline: {headline}"
        )
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        result = response.text.strip().strip('"\'')
        print(f"  -> Gemini Suggestion: {result}")
        return result
    except Exception as e:
        print(f"[ERROR] Gemini generation failed: {e}")
        return None

def render_channel_assets(session_dir=None):
    """Main rendering execution block creating localized branded templates."""
    session_dir = session_dir or get_latest_session_directory()
    if not session_dir or not os.path.exists(session_dir):
        print("[ERROR] No valid workspace session found to process.")
        return

    if not os.path.exists(CONFIG_FILE):
        print(f"[ERROR] Registry missing: {CONFIG_FILE}")
        return

    config = json.load(open(CONFIG_FILE, "r", encoding="utf-8"))
    channels = config.get("channels", {})

    raw_images = glob.glob(os.path.join(session_dir, "raw_image.*"))
    if not raw_images:
        print(f"[ERROR] No raw source image source file found in {session_dir}. Please supply 'raw_image.png/jpg'.")
        return

    # 1. Capture Global Area of Interest
    global_aoi = None
    if os.environ.get("DISPLAY") or os.name == 'nt': # Check for visual environment capability
        try:
            if input("[?] Define manual Area of Interest (AOI) for this batch? (y/n): ").strip().lower() in ['y', 'yes']:
                global_aoi = select_aoi_on_image(raw_images[0])
        except Exception:
            print("[i] Headless fallback activated or display init bypassed.")

    # 2. Iterate Channel Matrices
    for channel_name, profile in channels.items():
        lang_code = profile.get("language", "en")
        md_path = os.path.join(session_dir, f"{lang_code}.md")

        if not os.path.exists(md_path):
            print(f"  [SKIP] {channel_name}: Source file '{lang_code}.md' missing.")
            continue

        headline = extract_markdown_headline(md_path)
        if not headline:
            print(f"  [SKIP] {channel_name}: Empty content profile.")
            continue

        # Extract Layout Presets
        layout = profile.get("image_layout", {})
        template_path = os.path.join(PROJECT_ROOT, layout.get("template_overlay_path", ""))
        safe_area = layout.get("headline_safe_area", {})
        is_rtl = profile.get("is_rtl", False)

        if not os.path.exists(template_path):
            print(f"  [ERROR] {channel_name}: Overlay missing at {template_path}")
            continue

        # Master Canvas Fitment Initialization
        raw_img = Image.open(raw_images[0]).convert("RGBA")
        if global_aoi:
            center_x = (global_aoi[0][0] + global_aoi[1][0]) / 2
            center_y = (global_aoi[0][1] + global_aoi[1][1]) / 2
            img = ImageOps.fit(raw_img, (1000, 1000), centering=(center_x, center_y))
        else:
            img = ImageOps.fit(raw_img, (1000, 1000), centering=(0.5, 0.5))

        # Composition Overlay
        overlay = Image.open(template_path).convert("RGBA")
        img = Image.alpha_composite(img, overlay)

        draw = ImageDraw.Draw(img)
        font_path = os.path.join(PROJECT_ROOT, safe_area.get("font_path", ""))
        font_size = safe_area.get("font_size", 44)
        font_color = safe_area.get("font_color", "#FFFFFF")

        max_width = safe_area.get("width", 800)
        box_max_height = safe_area.get("max_height", 200)
        box_y_start = safe_area.get("y_start", 750)
        line_spacing = 10

        current_headline = headline
        resolved = False

        # 3. INTERACTIVE OVERFLOW EVALUATION ENGINE
        while not resolved:
            try:
                font = ImageFont.truetype(font_path, font_size)
            except IOError:
                font = ImageFont.load_default()

            # Reshape RTL logic dynamically to check boundaries accurately
            processed_text = arabic_reshaper.reshape(current_headline) if is_rtl else current_headline
            lines = wrap_text(processed_text, font, max_width, draw)

            bbox = font.getbbox("Agyپچ")
            line_height = bbox[3] - bbox[1]
            total_text_block_height = (len(lines) * line_height) + ((len(lines) - 1) * line_spacing)

            if total_text_block_height <= box_max_height:
                resolved = True
            else:
                print(f"\n[!] OVERFLOW DETECTED for channel [{channel_name}] (Required: {total_text_block_height}px, Max: {box_max_height}px)")
                print(f"    Content: \"{current_headline}\"")
                print("--------------------------------------------------------------------------------")
                print("  [1] Apply Automated Shrink-To-Fit Sequence (Reduces font size)")
                print("  [2] Manually rewrite/shorten a temporary headline for this layout")
                print("  [3] Call Gemini AI Instance to generate optimized alternative")
                print("--------------------------------------------------------------------------------")
                choice = input("[?] Select compensation strategy [1-3]: ").strip()

                if choice == "1":
                    print("  [~] Scaling down typography boundaries...")
                    while total_text_block_height > box_max_height and font_size > 14:
                        font_size -= 2
                        font = ImageFont.truetype(font_path, font_size)
                        lines = wrap_text(processed_text, font, max_width, draw)
                        total_text_block_height = (len(lines) * line_height) + ((len(lines) - 1) * line_spacing)
                    resolved = True
                elif choice == "2":
                    manual_input = input("    -> Enter updated temporary text: ").strip()
                    if manual_input:
                        current_headline = manual_input
                elif choice == "3":
                    ai_suggestion = shorten_headline_with_gemini(current_headline, lang_code)
                    if ai_suggestion:
                        current_headline = ai_suggestion
                else:
                    print("[!] Invalid choice. Defaulting to Shrink-to-fit bypass.")
                    choice = "1"

        # 4. Final Render and Coordinates Mapping
        y_offset = box_y_start + ((box_max_height - total_text_block_height) / 2)
        box_x_start = safe_area.get("x_start", 100)
        alignment = safe_area.get("alignment", "center")

        for line in lines:
            display_line = get_display(line) if is_rtl else line
            line_width = draw.textlength(display_line, font=font)

            if alignment == "center":
                x = box_x_start + ((max_width - line_width) / 2)
            elif alignment == "right":
                x = box_x_start + max_width - line_width
            else:
                x = box_x_start

            draw.text((x, y_offset), display_line, font=font, fill=font_color)
            y_offset += (line_height + line_spacing)

        # Commit Asset to Disk State
        output_filename = f"{channel_name}_broadcast.png"
        img.save(os.path.join(session_dir, output_filename), "PNG")
        print(f"  [+] Successfully Generated: {output_filename} (Final Font Size: {font_size}pt)")

    print("\n[SUCCESS] Graphic Engine loop iteration closed cleanly.")

if __name__ == "__main__":
    render_channel_assets()
