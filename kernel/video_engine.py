"""Video posts: every frame laid out the way image_engine lays out a photo, encoded with ffmpeg.

The channel template and the headline don't change from frame to frame, so they are drawn once
by image_engine onto a transparent layer. ffmpeg then places each frame on its blurred copy with
the numbers from image_engine.snippet_geometry() and puts that layer on top.

Not run on its own. Used by the web interface (pipeline_service: probe, prepare_files when a video
is uploaded or downloaded, render_channel_video as a background job) and by the terminal interface
(main.py: probe, stage_video; image_engine.render_channel_assets: LoopingFrames in the area window,
render_channel_video with terminal_progress).

ffmpeg comes from the imageio-ffmpeg package, or from PATH (on Termux: pkg install ffmpeg).

A video post's session folder holds, besides the texts:
    raw_video.<ext>               the source video (extension from its container, see CONTAINER_EXTENSIONS)
    video_frame.png               one frame: the "photo" for stills, the area of interest and thumbnails
    video_preview.mp4             a small silent copy any browser can play, for the area editors
    video_info.json               probe() details plus the frame's width and height
    <channel>_broadcast.jpg       the channel's still (image_engine), sent as the video's thumbnail
    <channel>_broadcast.mp4       the channel's video (render_channel_video)
"""
import os
import re
import json
import time
import shutil
import threading
import subprocess

# Imported before PIL (through image_engine) so the bundled FriBiDi is on PATH
from common import PROJECT_ROOT, RAW_VIDEO, VIDEO_INFO, VIDEO_FRAME, VIDEO_PREVIEW
import image_engine
from PIL import Image

try:
    import imageio_ffmpeg
except ImportError:
    imageio_ffmpeg = None

# File extension for each container ffmpeg reports; ffmpeg reads files by content, not by name
CONTAINER_EXTENSIONS = {"mov": ".mp4", "matroska": ".mkv", "avi": ".avi", "mpegts": ".ts", "mpeg": ".mpg",
                        "asf": ".wmv", "flv": ".flv"}
DEFAULT_EXTENSION = ".video"
# Offered by the terminal interface's file picker
VIDEO_FILE_EXTENSIONS = (".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".3gp", ".ts", ".mts", ".m2ts",
                         ".flv", ".wmv", ".mpg", ".mpeg")
# ffmpeg also reads still images as one-frame videos; these codecs mean "not a video"
IMAGE_CODECS = {"png", "mjpeg", "jpegls", "webp", "bmp", "tiff", "gif", "av1_image", "heif"}

# H.264 + AAC in MP4 plays everywhere and streams in Telegram
VIDEO_ARGS = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
AUDIO_ARGS = ["-c:a", "aac", "-b:a", "160k"]
# Height of the copy the browser plays in the area editor
PREVIEW_HEIGHT = 720

class VideoError(Exception):
    """A video that ffmpeg can't read or render; the message is meant for the user."""

def ffmpeg_exe():
    """ffmpeg bundled with imageio-ffmpeg, else the one on PATH (e.g. 'pkg install ffmpeg' on Termux)."""
    exe = imageio_ffmpeg.get_ffmpeg_exe() if imageio_ffmpeg else shutil.which("ffmpeg")
    if not exe:
        raise VideoError("ffmpeg isn't installed. Run the setup script again.")
    return exe

def run_ffmpeg(args):
    """Runs ffmpeg and returns its error output (where it prints file details)."""
    result = subprocess.run([ffmpeg_exe(), "-hide_banner", *args], capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    return result.returncode, result.stderr

def probe(path):
    """Reads a file's details from ffmpeg's output.

    Returns {"container" (e.g. "mov", "matroska"), "duration" (seconds or None), "codec", "hdr",
    "audio"}. Raises VideoError if the file has no video stream or is a still image.
    """
    _, output = run_ffmpeg(["-i", path])
    video = re.search(r"Stream #\S+.*?: Video: (\w+)(.*)", output)
    if not video or video.group(1) in IMAGE_CODECS:
        raise VideoError("This file isn't a video VTP can read.")
    container = re.search(r"Input #0, (\w+)", output)
    duration = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", output)
    return {
        "container": container.group(1) if container else None,
        "duration": int(duration[1]) * 3600 + int(duration[2]) * 60 + float(duration[3]) if duration else None,
        "codec": video.group(1),
        # PQ (HDR10, Dolby Vision) and HLG; phones record these as 10-bit HEVC
        "hdr": "smpte2084" in video.group(2) or "arib-std-b67" in video.group(2),
        "audio": bool(re.search(r"Stream #\S+.*?: Audio:", output)),
    }

def source_filters(info):
    """Filters applied to every decoded frame before anything else.

    Square pixels (some cameras store stretched frames), and HDR mapped to normal colours, which
    would otherwise look washed out. ffmpeg already turns phone videos the right way up.
    """
    filters = ["scale=trunc(iw*sar/2)*2:trunc(ih/2)*2", "setsar=1"]
    if info["hdr"]:
        # Tone mapping: to linear light (100 nits = SDR white), BT.709 primaries in float RGB,
        # the Hable curve compressing the highlights, then back to BT.709 gamma and TV range
        filters += ["zscale=t=linear:npl=100", "format=gbrpf32le", "zscale=p=bt709",
                    "tonemap=tonemap=hable:desat=0", "zscale=t=bt709:m=bt709:r=tv"]
    return filters

def extract_frame(video_path, out_path, info):
    """Saves one frame as a PNG, as the photo for the image engine (stills, thumbnails, the area editor).

    Takes the frame at 1 s, or halfway through shorter videos, since many start black.
    Returns (width, height), the size every frame is laid out at.
    """
    at = min(1.0, info["duration"] / 2) if info["duration"] else 0
    code, output = run_ffmpeg(["-v", "error", "-y", "-ss", f"{at:.3f}", "-i", video_path,
                               "-vf", ",".join(source_filters(info)), "-frames:v", "1", out_path])
    if code != 0 or not os.path.exists(out_path):
        raise VideoError(f"Couldn't read a frame from the video: {last_line(output)}")
    with Image.open(out_path) as img:
        return img.size

def last_line(output):
    """The last non-empty line of ffmpeg's output, usually the reason it failed."""
    lines = [l for l in output.strip().splitlines() if l.strip()]
    return lines[-1] if lines else "no details"

def snippet_filters(frame_size, target_size, aoi):
    """ffmpeg filters that turn a frame into the snippet image_engine.compose_image() pastes.

    Each mode of snippet_geometry() maps to the Pillow steps it stands for: "fit" is ImageOps.fit,
    "pad" is crop + ImageOps.pad, "crop" is resize + crop. Areas past the frame's edges become a
    transparent pad around it first, as Pillow's crop() does outside an image.
    """
    width, height = frame_size
    target_w, target_h = target_size
    geometry = image_engine.snippet_geometry(width, height, target_size, aoi)

    if geometry["mode"] == "fit":
        return [f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase:flags=bicubic",
                f"crop={target_w}:{target_h}"]

    filters = ["format=rgba"]
    min_x, min_y, max_x, max_y = (int(v) for v in geometry["bounds"])
    if (min_x, min_y, max_x, max_y) != (0, 0, width, height):
        filters.append(f"pad={max_x - min_x}:{max_y - min_y}:{-min_x}:{-min_y}:color=black@0")

    if geometry["mode"] == "pad":
        left, top, right, bottom = (int(v) for v in geometry["area"])
        return filters + [
            f"crop={right - left}:{bottom - top}:{left}:{top}",
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease:flags=bicubic",
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black@0",
        ]

    scaled_w, scaled_h = geometry["scaled_size"]
    crop_x, crop_y = geometry["window"][:2]
    return filters + [f"scale={scaled_w}:{scaled_h}:flags=lanczos",
                      f"crop={target_w}:{target_h}:{round(crop_x)}:{round(crop_y)}"]

def filter_graph(info, frame_size, layout, aoi, blur_radius):
    """The whole frame: blurred background, snippet, then the template and headline layer (input 1).

    Input 0 (the video) is split in two: one copy fills the canvas and is blurred [bg], the other
    becomes the snippet [fg], overlaid at raw_image_placement [base]. The template + headline
    PNG goes on top and the result [out] is converted for H.264.
    """
    placement = layout["raw_image_placement"]
    canvas_w, canvas_h = layout.get("canvas_size", [1000, 1000])
    target_size = (placement["width"], placement["height"])

    background = [f"scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=increase:flags=bicubic",
                  f"crop={canvas_w}:{canvas_h}"]
    if blur_radius:
        # Pillow's GaussianBlur radius is the standard deviation, like gblur's sigma
        background.append(f"gblur=sigma={blur_radius}")

    return ";".join([
        f"[0:v]{','.join(source_filters(info))},split=2[bgsrc][fgsrc]",
        f"[bgsrc]{','.join(background)}[bg]",
        f"[fgsrc]{','.join(snippet_filters(frame_size, target_size, aoi))}[fg]",
        f"[bg][fg]overlay={placement['x']}:{placement['y']}:format=rgb[base]",
        # H.264 in yuv420p needs even dimensions. Converted to, and labelled as, the BT.709 colours of HD video.
        "[base][1:v]overlay=0:0:format=rgb,crop=trunc(iw/2)*2:trunc(ih/2)*2,"
        "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,setsar=1,"
        "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv[out]",
    ])

def render_channel_video(session_dir, channel_name, profile, video_path, info, frame_size,
                         aoi=None, blur_radius=30, headline=None, font_size=None, on_progress=None, mute=False):
    """Renders <channel>_broadcast.mp4, the video counterpart of image_engine.render_channel().

    info comes from probe(), frame_size from extract_frame(). on_progress(fraction) is called
    while encoding. mute leaves the sound out; otherwise the first audio track (if any) is kept.
    The template + headline layer is written to <channel>_overlay.png for ffmpeg and removed after.
    Returns {"path", "headline", "font_size", "fits"}.
    """
    layout = profile["image_layout"]
    overlay = Image.open(os.path.join(PROJECT_ROOT, layout.get("template_overlay_path"))).convert("RGBA")
    result = image_engine.draw_channel_headline(overlay, session_dir, profile, headline, font_size)

    overlay_path = os.path.join(session_dir, f"{channel_name}_overlay.png")
    out_path = os.path.join(session_dir, f"{channel_name}_broadcast.mp4")
    overlay.save(overlay_path)
    try:
        encode(["-i", video_path, "-i", overlay_path,
                "-filter_complex", filter_graph(info, frame_size, layout, aoi, blur_radius),
                "-map", "[out]", *(["-an"] if mute else ["-map", "0:a:0?", *AUDIO_ARGS]), *VIDEO_ARGS],
               out_path, info["duration"], on_progress, f"render {channel_name}")
    finally:
        os.remove(overlay_path)

    return dict(result, path=out_path)

def prepare_files(video_path, frame_path, preview_path, info_path, info, on_progress=None):
    """Writes what a video post needs besides the video: its still frame, the small copy for
    playing it while the area is chosen, and its details (probe() info plus the frame size).

    on_progress(fraction) follows the copy, the slow part.
    """
    width, height = extract_frame(video_path, frame_path, info)
    make_preview(video_path, preview_path, info, on_progress)
    with open(info_path, "w", encoding="utf-8") as f:
        json.dump(dict(info, width=width, height=height), f, indent=2)

def terminal_progress(label):
    """An on_progress callback for the terminal: "[~] <label>... 42%", rewritten on one line."""
    def show(fraction):
        print(f"\r  [~] {label}... {fraction:.0%}", end="", flush=True)
    return show

def end_progress_line(message):
    """Replaces a terminal_progress() line with a final message."""
    print(f"\r{message}".ljust(70))

def stage_video(source_path, session_dir, info, on_progress=None):
    """Terminal interface: copies a video into a post folder as raw_video.<ext> and prepares its
    files there (the web interface prepares them at upload, in pipeline_service)."""
    raw_path = os.path.join(session_dir, RAW_VIDEO + CONTAINER_EXTENSIONS.get(info["container"], DEFAULT_EXTENSION))
    shutil.copy2(source_path, raw_path)
    prepare_files(raw_path, os.path.join(session_dir, VIDEO_FRAME), os.path.join(session_dir, VIDEO_PREVIEW),
                  os.path.join(session_dir, VIDEO_INFO), info, on_progress)
    return raw_path

class LoopingFrames:
    """Plays a video over and over, silently, as frames of the given size for a Tkinter window.

    ffmpeg loops the video (-stream_loop -1), turns it into fps frames per second and scales it.
    A thread takes one frame every 1/fps seconds and keeps it for latest(); ffmpeg waits while
    the pipe is full, so only a few frames exist at a time, whatever the video's length. ffmpeg's
    own -re pacing isn't used: with -stream_loop it lets frames through in bursts each time the
    video starts over. close() stops ffmpeg.
    """
    def __init__(self, video_path, size, fps=15):
        self.size = size
        self.fps = fps
        self.frame = None
        self.process = subprocess.Popen(
            [ffmpeg_exe(), "-hide_banner", "-v", "error", "-stream_loop", "-1", "-i", video_path,
             "-an", "-vf", f"fps={fps},scale={size[0]}:{size[1]}", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        frame_bytes = self.size[0] * self.size[1] * 3
        next_frame = time.monotonic()
        while True:
            data = self.process.stdout.read(frame_bytes)
            if len(data) < frame_bytes:
                return
            time.sleep(max(0, next_frame - time.monotonic()))
            self.frame = Image.frombytes("RGB", self.size, data)
            # Keeps the pace even if showing a frame was late
            next_frame = max(next_frame + 1 / self.fps, time.monotonic())

    def latest(self):
        """The most recent frame (a PIL image), or None before the first one arrives."""
        return self.frame

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()

def make_preview(video_path, out_path, info, on_progress=None):
    """A small silent H.264 copy for the browser's area editor; browsers can't play every format.

    It shows the same picture the frames are laid out from (upright, square pixels, HDR mapped).
    """
    scale = f"scale=-2:'min({PREVIEW_HEIGHT},ih)'"
    encode(["-i", video_path, "-vf", ",".join(source_filters(info) + [scale, "format=yuv420p"]),
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28"],
           out_path, info["duration"], on_progress, "prepare the video")

def encode(args, out_path, duration, on_progress, action):
    """Runs an ffmpeg encode to out_path, reporting progress as a fraction of duration.

    Writes to a .part file first, so a failed or stopped encode never replaces a good file.
    An exception raised by on_progress (e.g. to cancel) stops ffmpeg and is passed on.
    ffmpeg's -progress output (key=value lines on stdout) gives out_time_us, the time encoded so far.
    "+faststart" puts the index at the start of the MP4, so Telegram and browsers can stream it.
    """
    root, ext = os.path.splitext(out_path)
    part_path = f"{root}.part{ext}"
    process = subprocess.Popen([ffmpeg_exe(), "-hide_banner", "-v", "error", "-nostats", "-progress", "pipe:1",
                                "-y", *args, "-movflags", "+faststart", part_path],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               encoding="utf-8", errors="replace")
    try:
        for line in process.stdout:
            key, _, value = line.strip().partition("=")
            if on_progress and key == "out_time_us" and value.isdigit() and duration:
                on_progress(min(1.0, int(value) / 1e6 / duration))
        errors = process.stderr.read()
        if process.wait() != 0:
            raise VideoError(f"ffmpeg couldn't {action}: {last_line(errors)}")
        os.replace(part_path, out_path)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        if os.path.exists(part_path):
            os.remove(part_path)
