"""Post (session folder) operations for the web interface, built on the engines' functions."""
import io
import os
import re
import glob
import json
import uuid
import shutil
import datetime

# Imported before PIL (through image_engine) so the bundled FriBiDi is on PATH
from common import WORKSPACE_DIR, load_channels_config, load_gemini_credentials, save_gemini_credentials
import text_engine
import image_engine
import publisher
from PIL import Image

# Photos uploaded from the browser or downloaded from a chat, before a post exists
UPLOADS_DIR = os.path.join(WORKSPACE_DIR, "web_uploads")
MAX_UPLOAD_BYTES = 30 * 1024 * 1024
UPLOAD_NAME = re.compile(r"[0-9a-f]{32}\.(jpg|png|webp)")
UPLOAD_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}

SESSION_NAME = re.compile(r"session_[0-9A-Za-z_-]+")
SESSION_IMAGE = re.compile(r"[0-9A-Za-z_.-]+\.(jpg|jpeg|png|webp)", re.IGNORECASE)
LANGUAGE_CODE = re.compile(r"[a-z]{2,3}")

# Web-only state kept next to the session's files; the terminal pipeline ignores these
RENDER_SETTINGS_FILE = "web_render.json"
PUBLISH_LOG_FILE = "web_publish_log.json"
DEFAULT_BLUR = 30
MAX_BLUR = 100

class PostError(Exception):
    """A problem the user can fix; the message is shown in the browser."""

class PostNotFound(Exception):
    """An unknown post, channel, photo or file."""

# ==========================================
# SESSIONS
# ==========================================
def session_path(name):
    """Absolute path of a session folder. Raises PostNotFound for unknown or malformed names."""
    path = os.path.join(WORKSPACE_DIR, name)
    if not SESSION_NAME.fullmatch(name) or not os.path.isdir(path):
        raise PostNotFound(f"No post named {name}.")
    return path

def session_created(name):
    match = re.match(r"session_(\d{8}_\d{6})", name)
    if not match:
        return None
    return datetime.datetime.strptime(match.group(1), "%Y%m%d_%H%M%S").isoformat()

def read_text(session_dir, lang):
    """(headline, body) from <lang>.md, split the way the caption builder splits it; None if missing."""
    path = os.path.join(session_dir, f"{lang}.md")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    headline = lines[0].lstrip("#").strip() if lines else ""
    return headline, "".join(lines[1:]).strip()

def write_text(session_dir, lang, headline, body):
    if not LANGUAGE_CODE.fullmatch(lang):
        raise PostError(f"Unknown language code: {lang}")
    headline = " ".join(headline.split())  # The headline must stay on the first line
    with open(os.path.join(session_dir, f"{lang}.md"), "w", encoding="utf-8") as f:
        f.write(f"# {headline}\n\n{body.strip()}\n")

def channel_languages(config, session_dir=None):
    """English first, then the channels' languages in config order, then any other <lang>.md."""
    languages = ["en"]
    for profile in config.get("channels", {}).values():
        lang = profile.get("language", "en").lower()
        if lang not in languages:
            languages.append(lang)
    if session_dir:
        for path in sorted(glob.glob(os.path.join(session_dir, "*.md"))):
            lang = os.path.splitext(os.path.basename(path))[0]
            if LANGUAGE_CODE.fullmatch(lang) and lang not in languages:
                languages.append(lang)
    return languages

def mtime(path):
    return os.path.getmtime(path) if os.path.exists(path) else None

def list_sessions(limit=100):
    """The newest posts first, with what has been done in each."""
    folders = [p for p in glob.glob(os.path.join(WORKSPACE_DIR, "session_*")) if os.path.isdir(p)]
    sessions = []
    for path in sorted(folders, reverse=True)[:limit]:
        name = os.path.basename(path)
        title = (read_text(path, "en") or ("", ""))[0]
        images = sorted(os.path.basename(p) for p in glob.glob(os.path.join(path, "*_broadcast.jpg")))
        raw = image_engine.find_raw_image(path)
        thumbnail = images[0] if images else (os.path.basename(raw) if raw else None)
        log = load_publish_log(path)
        sessions.append({
            "name": name,
            "created": session_created(name),
            "title": title or name,
            "thumbnail": thumbnail,
            "thumbnail_version": int(mtime(os.path.join(path, thumbnail))) if thumbnail else None,
            "images": len(images),
            "previews": len(log.get("previews", {})),
            "published": len([e for e in log.get("published", {}).values() if e.get("msg_id")]),
        })
    return sessions

# ==========================================
# NEW POSTS
# ==========================================
def save_upload(data):
    """Stores an uploaded photo and returns its token. Raises PostError if it isn't a JPG/PNG/WebP."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise PostError("The photo is larger than 30 MB.")
    try:
        with Image.open(io.BytesIO(data)) as img:
            image_format = img.format
            img.verify()
    except Exception:
        raise PostError("This file isn't a photo VTP can read. Use JPG or PNG.")
    if image_format not in UPLOAD_FORMATS:
        raise PostError(f"{image_format} photos aren't supported. Use JPG or PNG.")

    os.makedirs(UPLOADS_DIR, exist_ok=True)
    token = uuid.uuid4().hex + UPLOAD_FORMATS[image_format]
    with open(os.path.join(UPLOADS_DIR, token), "wb") as f:
        f.write(data)
    return token

def new_download_path():
    """Path without extension for a photo downloaded from Telegram; Telethon adds the extension."""
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    return os.path.join(UPLOADS_DIR, "download_" + uuid.uuid4().hex)

def adopt_download(path):
    """Checks a photo downloaded from Telegram like an upload and returns its token."""
    try:
        with open(path, "rb") as f:
            return save_upload(f.read())
    finally:
        os.remove(path)

def clean_uploads(max_age_days=7):
    """Deletes uploaded photos older than max_age_days; a post keeps its own copy (raw_image.*)."""
    cutoff = datetime.datetime.now().timestamp() - max_age_days * 86400
    for path in glob.glob(os.path.join(UPLOADS_DIR, "*")):
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            pass

def upload_path(token):
    path = os.path.join(UPLOADS_DIR, token)
    if not UPLOAD_NAME.fullmatch(token) or not os.path.isfile(path):
        raise PostNotFound("The chosen photo is no longer available. Choose it again.")
    return path

def create_session(raw_text, image_token, model=None):
    """Translates the text with Gemini, creates the session folder and stages the photo.

    Returns the session name. Raises PostError with a readable message when Gemini fails,
    so the user can try another model.
    """
    image = upload_path(image_token)
    clean_text = text_engine.sanitize_clipboard_text(raw_text or "")
    if not clean_text:
        raise PostError("The text is empty.")

    profile = load_gemini_credentials()
    api_key = profile.get("gemini_api_key")
    if not api_key:
        raise PostError("No Gemini API key saved. Add one on the Setup page.")
    model = model or profile.get("last_used_model")

    try:
        parsed = text_engine.request_translation(clean_text, api_key, model)
    except Exception as e:
        raise PostError(f"Gemini ({model}) failed: {e}. Choose another model and try again.")
    if not isinstance(parsed, dict) or not any(isinstance(v, dict) for v in parsed.values()):
        raise PostError(f"Gemini ({model}) returned no usable texts. Try again or choose another model.")

    save_gemini_credentials(api_key, model)
    session_dir = text_engine.save_session(parsed)

    _, ext = os.path.splitext(image)
    shutil.copy2(image, os.path.join(session_dir, f"raw_image{ext.lower()}"))
    ensure_captions(session_dir)
    return os.path.basename(session_dir)

# ==========================================
# IMAGES
# ==========================================
def load_render_settings(session_dir):
    path = os.path.join(session_dir, RENDER_SETTINGS_FILE)
    settings = {"aoi": None, "blur": DEFAULT_BLUR, "overrides": {}}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            settings.update(json.load(f))
    return settings

def save_render_settings(session_dir, settings):
    with open(os.path.join(session_dir, RENDER_SETTINGS_FILE), "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)

def set_render_options(session_dir, aoi, blur):
    """aoi is [left, top, right, bottom] in photo pixels (may extend past the edges) or None."""
    if aoi is not None:
        if len(aoi) != 4 or aoi[0] >= aoi[2] or aoi[1] >= aoi[3]:
            raise PostError("The area of interest needs two different corners.")
        aoi = [int(round(v)) for v in aoi]
    if not 0 <= blur <= MAX_BLUR:
        raise PostError(f"Blur must be between 0 and {MAX_BLUR}.")
    settings = load_render_settings(session_dir)
    settings["aoi"], settings["blur"] = aoi, int(blur)
    save_render_settings(session_dir, settings)

def channel_profile(config, channel):
    profile = config.get("channels", {}).get(channel)
    if not profile:
        raise PostNotFound(f"No channel named {channel} in channels.json.")
    return profile

def image_headline(session_dir, channel, profile, settings):
    """The headline and font size drawn on a channel's image, with any per-channel override applied."""
    lang = profile.get("language", "en").lower()
    override = settings["overrides"].get(channel, {})
    headline = override.get("headline")
    if headline is None:
        headline = image_engine.extract_markdown_headline(os.path.join(session_dir, f"{lang}.md"))
    style = image_engine.headline_style(profile["image_layout"], profile.get("is_rtl", False))
    return headline, override.get("font_size") or style["font_size"], style

def headline_fits(headline, style, font_size, profile):
    if not headline:
        return True
    is_rtl = profile.get("is_rtl", False)
    lang = profile.get("language", "en").lower()
    layout = image_engine.layout_headline(headline, style, font_size, is_rtl, lang, image_engine.make_rtl_reshaper(is_rtl))
    return layout["fits"]

def render_channels(session_dir, channels=None):
    """Renders the given channels (all by default) with the saved area, blur and overrides."""
    config = load_channels_config()
    raw_path = image_engine.find_raw_image(session_dir)
    if not raw_path:
        raise PostError("This post has no photo (raw_image.*).")
    settings = load_render_settings(session_dir)
    aoi = tuple(settings["aoi"]) if settings["aoi"] else None

    for name, profile in config.get("channels", {}).items():
        if channels is not None and name not in channels:
            continue
        override = settings["overrides"].get(name, {})
        image_engine.render_channel(session_dir, name, profile, raw_path, aoi, settings["blur"],
                                    override.get("headline"), override.get("font_size"))

def set_override(session_dir, channel, headline=None, font_size=None):
    """Sets the image-only headline and/or font size of a channel; both None removes the override."""
    channel_profile(load_channels_config(), channel)
    settings = load_render_settings(session_dir)
    override = {}
    if headline is not None:
        override["headline"] = " ".join(headline.split())
    if font_size is not None:
        override["font_size"] = int(font_size)
    if override:
        settings["overrides"][channel] = override
    else:
        settings["overrides"].pop(channel, None)
    save_render_settings(session_dir, settings)
    render_channels(session_dir, [channel])

def shrink_to_fit(session_dir, channel):
    """Overflow option 1: lowers the font size until the headline fits (down to MIN_FONT_SIZE)."""
    config = load_channels_config()
    profile = channel_profile(config, channel)
    settings = load_render_settings(session_dir)
    headline, font_size, style = image_headline(session_dir, channel, profile, settings)
    is_rtl = profile.get("is_rtl", False)
    lang = profile.get("language", "en").lower()
    new_size = image_engine.shrink_font_size(headline, style, font_size, is_rtl, lang, image_engine.make_rtl_reshaper(is_rtl))
    override = settings["overrides"].get(channel, {})
    set_override(session_dir, channel, override.get("headline"), new_size)

def shorten_with_gemini(session_dir, channel):
    """Overflow option 2: asks Gemini for a shorter headline (image only) and re-renders."""
    if not image_engine.genai:
        raise PostError("The Gemini SDK (google-genai) isn't installed.")
    profile_creds = load_gemini_credentials()
    if not profile_creds.get("gemini_api_key"):
        raise PostError("No Gemini API key saved. Add one on the Setup page.")
    config = load_channels_config()
    profile = channel_profile(config, channel)
    headline, _, _ = image_headline(session_dir, channel, profile, load_render_settings(session_dir))
    model = profile_creds.get("last_used_model")
    try:
        shorter = image_engine.shorten_headline_with_gemini(
            headline, profile.get("language", "en").lower(), profile_creds["gemini_api_key"], model)
    except Exception as e:
        raise PostError(f"Gemini ({model}) couldn't shorten the headline: {e}")
    set_override(session_dir, channel, shorter, None)

# ==========================================
# CAPTIONS
# ==========================================
def caption_path(session_dir, channel):
    return os.path.join(session_dir, f"{channel}_caption.txt")

def ensure_captions(session_dir):
    """Creates the missing caption files, like the terminal publisher. Existing ones are kept."""
    config = load_channels_config()
    for name, profile in config.get("channels", {}).items():
        md_path = os.path.join(session_dir, f"{profile.get('language', 'en')}.md")
        if not os.path.exists(caption_path(session_dir, name)) and os.path.exists(md_path):
            write_caption(session_dir, name, publisher.build_caption(md_path, profile))

def write_caption(session_dir, channel, text):
    with open(caption_path(session_dir, channel), "w", encoding="utf-8") as f:
        f.write(text)

def save_caption(session_dir, channel, text):
    channel_profile(load_channels_config(), channel)
    write_caption(session_dir, channel, text)

def rebuild_caption(session_dir, channel):
    """Recreates a caption from the current <lang>.md, discarding manual edits."""
    profile = channel_profile(load_channels_config(), channel)
    md_path = os.path.join(session_dir, f"{profile.get('language', 'en')}.md")
    if not os.path.exists(md_path):
        raise PostError(f"There is no {profile.get('language', 'en')}.md text for this channel.")
    write_caption(session_dir, channel, publisher.build_caption(md_path, profile))

# ==========================================
# PUBLISH LOG
# ==========================================
def load_publish_log(session_dir):
    path = os.path.join(session_dir, PUBLISH_LOG_FILE)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_publish_log(session_dir, log):
    with open(os.path.join(session_dir, PUBLISH_LOG_FILE), "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)

def record_sent(session_dir, kind, channel, message):
    """Remembers where a preview ("previews") or live post ("published") went, or that it failed.

    log[kind][channel] holds the latest attempt. Every preview message is also kept in
    log["preview_messages"], so all of them can be deleted once the channel is published.
    """
    log = load_publish_log(session_dir)
    entry = {"date": datetime.datetime.now().isoformat(timespec="seconds")}
    if message:
        entry.update(chat_id=message.chat_id, msg_id=message.id)
        if kind == "previews":
            log.setdefault("preview_messages", []).append(
                {"channel": channel, "chat_id": message.chat_id, "msg_id": message.id})
    else:
        entry["failed"] = True
    log.setdefault(kind, {})[channel] = entry
    save_publish_log(session_dir, log)

def previews_of(session_dir, channels):
    """The preview messages still in the review channel for these channels: [{channel, chat_id, msg_id}]."""
    log = load_publish_log(session_dir)
    return [p for p in log.get("preview_messages", []) if p["channel"] in channels]

def forget_previews(session_dir, deleted):
    """Drops deleted preview messages from the log and marks their channels' latest preview as removed."""
    log = load_publish_log(session_dir)
    gone = {(p["chat_id"], p["msg_id"]) for p in deleted}
    log["preview_messages"] = [p for p in log.get("preview_messages", []) if (p["chat_id"], p["msg_id"]) not in gone]
    for p in deleted:
        latest = log.get("previews", {}).get(p["channel"])
        if latest and (latest.get("chat_id"), latest.get("msg_id")) == (p["chat_id"], p["msg_id"]):
            latest["removed"] = True
    save_publish_log(session_dir, log)

# ==========================================
# POST DETAILS
# ==========================================
def session_detail(name):
    """Everything the post page shows: texts, photo, render settings, channels, captions, publish log."""
    session_dir = session_path(name)
    config = load_channels_config()
    ensure_captions(session_dir)
    settings = load_render_settings(session_dir)

    languages = []
    for lang in channel_languages(config, session_dir):
        text = read_text(session_dir, lang)
        languages.append({"code": lang, "exists": text is not None,
                          "headline": text[0] if text else "", "body": text[1] if text else ""})

    raw_path = image_engine.find_raw_image(session_dir)
    raw_image = None
    if raw_path:
        with Image.open(raw_path) as img:
            raw_image = {"file": os.path.basename(raw_path), "version": int(mtime(raw_path)),
                         "width": img.width, "height": img.height}

    log = load_publish_log(session_dir)
    channels = []
    for channel, profile in config.get("channels", {}).items():
        lang = profile.get("language", "en").lower()
        md_time = mtime(os.path.join(session_dir, f"{lang}.md"))
        headline, font_size, style = image_headline(session_dir, channel, profile, settings)
        image_file = os.path.join(session_dir, f"{channel}_broadcast.jpg")
        image_time = mtime(image_file)
        caption_file = caption_path(session_dir, channel)
        caption_time = mtime(caption_file)
        caption = None
        if caption_time:
            with open(caption_file, "r", encoding="utf-8") as f:
                caption = f.read()
        channels.append({
            "name": channel,
            "language": lang,
            "is_rtl": profile.get("is_rtl", False),
            "has_target": bool(publisher.parse_target(profile.get("chat_id"))),
            "headline": headline or "",
            "font_size": font_size,
            "base_font_size": style["font_size"],
            "override": settings["overrides"].get(channel, {}),
            "fits": headline_fits(headline, style, font_size, profile),
            "image": {"file": os.path.basename(image_file), "version": int(image_time)} if image_time else None,
            # The text was edited after the image or caption was made from it
            "image_outdated": bool(image_time and md_time and image_time < md_time),
            "caption": caption,
            "caption_outdated": bool(caption_time and md_time and caption_time < md_time),
            "preview": log.get("previews", {}).get(channel),
            "published": log.get("published", {}).get(channel),
        })

    return {
        "name": name,
        "created": session_created(name),
        "title": (read_text(session_dir, "en") or (name, ""))[0],
        "languages": languages,
        "raw_image": raw_image,
        "render": {"aoi": settings["aoi"], "blur": settings["blur"]},
        "channels": channels,
        "review_channel": config.get("catch_all_channel") or None,
        # Previews still in the review channel (deleted once their channel is published)
        "pending_previews": len(log.get("preview_messages", [])),
    }

def session_file(name, filename):
    """Path of an image inside a session folder (raw photo or rendered image)."""
    path = os.path.join(session_path(name), filename)
    if not SESSION_IMAGE.fullmatch(filename) or not os.path.isfile(path):
        raise PostNotFound("No such image.")
    return path
