"""VTP web interface: a local web server over the same engines and session folders as the terminal tools.

Start it with run-web.bat (Windows) or `bash run-web.sh` (Linux, Termux), which check the venv first,
or directly with `python -B kernel/webapp.py [--port 8765] [--no-browser]`. It serves the page in
kernel/web/ at http://127.0.0.1:<port>/ and opens it in the default browser. Stop it with Ctrl+C.

It listens on 127.0.0.1 only, so only this device can use it. The middleware below also refuses
requests addressed to other host names (DNS rebinding) and non-GET requests from other websites, and
sets a strict Content-Security-Policy. POST bodies are JSON, except uploads, which are raw image/video bodies.

Routes:
  /, /static/*, /fonts/*   the page, its scripts and styles, and the fonts in _config/fonts
  /api/status, /api/setup/*, /api/login/*, /api/telegram/reconnect   Setup tab
  /api/telegram/*          Telegram tab: chats, messages, images, reactions (telegram_service)
  /api/events              live updates (server-sent events): Telegram changes and job progress
  /api/uploads*, /api/sessions*, /api/gemini/models, /api/jobs/*   posts (pipeline_service)

Long work runs as background jobs in send_jobs: sending previews or live posts (publisher), and
rendering a video post's videos (video_engine through pipeline_service). The page follows them
through "job" events. Jobs are kept in memory only; a restart forgets them.

Files: _credentials/ (Telegram session and API keys, Gemini key), _config/channels.json (read),
_workspace/session_*/ (posts, incl. web_render.json and web_publish_log.json), and the caches
_workspace/web_cache/ and _workspace/web_uploads/ (cleaned at start-up, 7 days).

Telethon's session file can be used by one program at a time: close the terminal tools while this runs.
"""
import sys
# Prevent the creation of __pycache__ folders
sys.dont_write_bytecode = True

import os
import re
import json
import shutil
import asyncio
import argparse
import datetime
import mimetypes
import threading
import subprocess
import webbrowser
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

# Imported before PIL (through image_engine) so the bundled FriBiDi is on PATH
from common import (
    PROJECT_ROOT, CONFIG_FILE,
    load_channels_config, load_gemini_credentials, save_gemini_credentials, list_gemini_models,
)
import image_engine
import publisher
import pipeline_service
from publisher import parse_target
from pipeline_service import PostError, PostNotFound
from telegram_service import TelegramService, clean_web_cache

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

WEB_DIR = os.path.join(PROJECT_ROOT, "kernel", "web")  # index.html, app.js, posts.js, style.css
FONTS_DIR = os.path.join(PROJECT_ROOT, "_config", "fonts")
DEFAULT_PORT = 8765

# Older Pythons don't know .avif; the file would be sent with a generic type, and with "nosniff" the browser won't show it
mimetypes.add_type("image/avif", ".avif")

# The server only listens on 127.0.0.1. Checking the Host header as well stops other
# websites from reaching it through DNS rebinding (a domain that resolves to 127.0.0.1).
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}

# Only the page's own files: no inline scripts or style attributes, no outside sites.
# blob: lets the New post page preview a chosen photo or video before it's uploaded.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self'; script-src 'self'; "
    "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)

# The one Telegram client of the server, shared by every route
telegram = TelegramService()

@asynccontextmanager
async def lifespan(app):
    """Start-up: removes cache and upload files older than 7 days and connects to Telegram. Shutdown: disconnects."""
    clean_web_cache()
    pipeline_service.clean_uploads()
    # Connecting can take a while (or time out when offline); the page loads meanwhile
    start_task = asyncio.create_task(telegram.start())
    yield
    start_task.cancel()
    await telegram.stop()

app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

@app.middleware("http")
async def local_requests_only(request: Request, call_next):
    """Refuses requests for other host names and cross-site commands; adds security headers to every response."""
    if urlsplit("//" + request.headers.get("host", "")).hostname not in ALLOWED_HOSTS:
        return JSONResponse({"detail": "Unknown host."}, status_code=403)

    # Blocks other websites from sending commands (e.g. a hidden form posting to 127.0.0.1)
    if request.method not in ("GET", "HEAD"):
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).hostname not in ALLOWED_HOSTS:
            return JSONResponse({"detail": "Cross-site request refused."}, status_code=403)

    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response

def require_telegram():
    """Stops a request that needs Telegram while the account isn't logged in (503)."""
    if telegram.state != "ready":
        raise HTTPException(503, "Telegram is not logged in. Open the Setup page.")

async def telegram_call(coro):
    """Awaits a Telegram request, turning its errors into a readable HTTP error.

    ValueError (bad input, e.g. an unknown chat or a wrong login code) -> 400; anything else -> 502.
    """
    try:
        return await coro
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Telegram: {e}")

# ==========================================
# PAGE AND STATIC FILES
# ==========================================
# "no-cache" makes the browser check for a newer version on every load (answered with 304 when unchanged),
# so an updated app.js, posts.js or style.css is used after a normal reload
class PageFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response

@app.get("/")
async def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"), headers={"Cache-Control": "no-cache"})

app.mount("/static", PageFiles(directory=WEB_DIR), name="static")

@app.get("/fonts/{name}")
async def font_file(name: str):
    """Serves fonts from _config/fonts so Persian, Arabic and Kurdish text uses the same font as the images."""
    path = os.path.join(FONTS_DIR, name)
    if not re.fullmatch(r"[\w.-]+\.(ttf|otf|woff2?)", name) or not os.path.isfile(path):
        raise HTTPException(404)
    return FileResponse(path)

# ==========================================
# STATUS AND SETUP
# ==========================================
@app.get("/api/status")
async def status():
    """Everything the Setup tab and the connection dot show: Telegram state, Gemini key, Raqm, channels.json."""
    gemini = load_gemini_credentials()
    config_info = {"exists": os.path.exists(CONFIG_FILE), "channels": 0, "error": None}
    if config_info["exists"]:
        try:
            config_info["channels"] = len(load_channels_config().get("channels", {}))
        except Exception as e:
            config_info["error"] = str(e)
    return {
        "telegram": telegram.status(),
        "gemini": {"key_set": bool(gemini.get("gemini_api_key")), "model": gemini.get("last_used_model")},
        "raqm": image_engine.RAQM_AVAILABLE,
        "config": config_info,
    }

class ApiCredentials(BaseModel):
    api_id: int
    api_hash: str

@app.post("/api/setup/telegram-api")
async def setup_telegram_api(body: ApiCredentials):
    """Saves the API ID and hash from my.telegram.org (_credentials/telegram_api.json) and connects with them."""
    api_hash = body.api_hash.strip()
    if not re.fullmatch(r"[0-9a-fA-F]{32}", api_hash):
        raise HTTPException(400, "api_hash should be 32 hexadecimal characters, as shown on my.telegram.org.")
    await telegram.save_api_credentials(body.api_id, api_hash)
    return telegram.status()

@app.post("/api/telegram/reconnect")
async def telegram_reconnect():
    await telegram.restart()
    return telegram.status()

# Login takes up to three steps: phone number -> code sent by Telegram -> two-step verification password
class PhoneBody(BaseModel):
    phone: str

class CodeBody(BaseModel):
    code: str

class PasswordBody(BaseModel):
    password: str

def require_login_client():
    """Login steps need a connected client; it may be logged out, or already logged in (switching steps)."""
    if not telegram.client or telegram.state not in ("logged_out", "ready"):
        raise HTTPException(503, "Telegram is not connected. " + (telegram.error or ""))

@app.post("/api/login/phone")
async def login_phone(body: PhoneBody):
    require_login_client()
    await telegram_call(telegram.send_code(body.phone.strip()))
    return telegram.status()

@app.post("/api/login/code")
async def login_code(body: CodeBody):
    require_login_client()
    if not telegram.login_phone:
        raise HTTPException(400, "Request a login code first.")
    await telegram_call(telegram.submit_code(body.code.strip()))
    return telegram.status()

@app.post("/api/login/password")
async def login_password(body: PasswordBody):
    require_login_client()
    await telegram_call(telegram.submit_password(body.password))
    return telegram.status()

class GeminiKeyBody(BaseModel):
    api_key: str

@app.post("/api/setup/gemini")
async def setup_gemini(body: GeminiKeyBody):
    """Saves the Gemini key (keeping the last used model), then lists the models to check that the key works."""
    api_key = body.api_key.strip()
    if not api_key:
        raise HTTPException(400, "Paste a key from Google AI Studio.")
    save_gemini_credentials(api_key, load_gemini_credentials().get("last_used_model"))
    try:
        models = await run_in_threadpool(list_gemini_models, api_key)
    except Exception as e:
        return {"saved": True, "warning": f"Key saved, but listing models failed: {e}"}
    return {"saved": True, "models": len(models)}

# ==========================================
# TELEGRAM TAB
# ==========================================
# Reading chats doesn't mark anything as read. Reacting is the only thing here that changes Telegram.
@app.get("/api/telegram/shortcuts")
async def telegram_shortcuts():
    """The review channel and every live channel from channels.json (by name), for the top of the chat list.

    A channel ID that can't be found is returned with the reason instead of failing the whole list.
    """
    require_telegram()
    try:
        config = load_channels_config()
    except Exception:
        return []

    targets = []
    if parse_target(config.get("catch_all_channel")):
        targets.append(("Review channel", parse_target(config["catch_all_channel"])))
    for name, profile in sorted(config.get("channels", {}).items()):
        if parse_target(profile.get("chat_id")):
            targets.append((name, parse_target(profile["chat_id"])))
    return await telegram_call(telegram.resolve_shortcuts(targets))

@app.get("/api/telegram/dialogs")
async def telegram_dialogs(offset_date: str = None):
    """A page of the chat list; offset_date (the last chat's date) asks for the next, older page."""
    require_telegram()
    offset = datetime.datetime.fromisoformat(offset_date) if offset_date else None
    return await telegram_call(telegram.list_dialogs(offset))

@app.get("/api/telegram/chats/{chat_id}")
async def telegram_chat(chat_id: int):
    require_telegram()
    return await telegram_call(telegram.chat_info(chat_id))

@app.get("/api/telegram/chats/{chat_id}/messages")
async def telegram_messages(chat_id: int, offset_id: int = 0):
    """The newest messages of a chat, or those older than offset_id ("Load older")."""
    require_telegram()
    return await telegram_call(telegram.list_messages(chat_id, offset_id))

@app.get("/api/telegram/chats/{chat_id}/messages/{msg_id}")
async def telegram_message(chat_id: int, msg_id: int):
    require_telegram()
    message = await telegram_call(telegram.get_message(chat_id, msg_id))
    if not message:
        raise HTTPException(404, "Message not found.")
    return message

@app.get("/api/telegram/chats/{chat_id}/messages/{msg_id}/reactions")
async def telegram_reactors(chat_id: int, msg_id: int):
    """Who reacted with what ("Who reacted"); channels keep reactions anonymous."""
    require_telegram()
    return await telegram_call(telegram.list_reactors(chat_id, msg_id))

@app.get("/api/telegram/chats/{chat_id}/reaction-menu")
async def telegram_reaction_menu(chat_id: int):
    """The reactions the picker offers in this chat: your recent ones and all the chat allows."""
    require_telegram()
    return await telegram_call(telegram.reaction_menu(chat_id))

class ReactionItem(BaseModel):
    emoji: str | None = Field(None, max_length=16)
    custom_emoji_id: str | None = Field(None, pattern=r"^\d{1,20}$")

class ReactionBody(BaseModel):
    reactions: list[ReactionItem] = Field(max_length=3)  # an empty list removes your reaction

@app.post("/api/telegram/chats/{chat_id}/messages/{msg_id}/reaction")
async def telegram_react(chat_id: int, msg_id: int, body: ReactionBody):
    """Reacts to a message as your account, replacing your previous reaction (the one Telegram change in this tab)."""
    require_telegram()
    if any(not (r.emoji or r.custom_emoji_id) for r in body.reactions):
        raise HTTPException(400, "Each reaction needs an emoji or a custom emoji ID.")
    reactions = [r.model_dump(exclude_none=True) for r in body.reactions]
    return await telegram_call(telegram.send_reaction(chat_id, msg_id, reactions))

def image_response(path, missing_message):
    """Sends a file from the image cache (_workspace/web_cache/); the browser may keep it for a day."""
    if not path or not os.path.exists(path):
        raise HTTPException(404, missing_message)
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})

@app.get("/api/telegram/media/{chat_id}/{msg_id}")
async def telegram_media(chat_id: int, msg_id: int):
    """The image shown for a message in the chat: its photo, a file's or video's thumbnail, or a link preview."""
    require_telegram()
    path = await telegram_call(telegram.preview_image(chat_id, msg_id))
    return image_response(path, "This message has no image.")

@app.get("/api/telegram/avatar/{chat_id}/{photo_id}")
async def telegram_avatar(chat_id: int, photo_id: int):
    require_telegram()
    path = await telegram_call(telegram.profile_photo(chat_id, photo_id))
    return image_response(path, "No profile picture.")

@app.get("/api/telegram/custom-emoji/{document_id}")
async def telegram_custom_emoji(document_id: int):
    require_telegram()
    path = await telegram_call(telegram.custom_emoji_image(document_id))
    return image_response(path, "This custom emoji has no still image.")

@app.get("/api/events")
async def live_events(request: Request):
    """Server-sent events: new, edited and deleted messages, reaction changes, and job progress.

    Each event is one JSON object with a "type". A comment line every 15 s keeps the connection open;
    the browser reconnects by itself after 3 s if it drops.
    """
    queue = telegram.subscribe()

    async def stream():
        try:
            yield "retry: 3000\n\n"
            while not await request.is_disconnected():
                try:
                    update = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"data: {json.dumps(update)}\n\n"
        finally:
            telegram.unsubscribe(queue)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

# ==========================================
# POSTS (THE PIPELINE)
# ==========================================
# A post is a session folder in _workspace/; pipeline_service does the file work, these routes add
# locking and background jobs.
#
# Rendering images writes the session's files and render settings; one render at a time avoids two writers
render_lock = asyncio.Lock()
# ffmpeg uses every CPU core, so video posts render one job at a time (other jobs wait their turn)
video_lock = asyncio.Lock()
# Background jobs, job ID -> state dict pushed to the page as it changes. Kinds: "previews" (to the
# review channel), "published" (to the live channels), "videos" (rendering a video post's videos).
# Common keys: id, session, kind, channels, status ("running", "done", "failed", "replaced"),
# results (channel -> {"ok", ...}), error.
send_jobs = {}
MAX_KEPT_JOBS = 50  # the oldest finished jobs are forgotten beyond this
SEND_KINDS = ("previews", "published")

async def post_call(func, *args, **kwargs):
    """Runs a pipeline_service function in a worker thread, turning its errors into HTTP errors."""
    try:
        return await run_in_threadpool(func, *args, **kwargs)
    except PostError as e:
        raise HTTPException(400, str(e))
    except PostNotFound as e:
        raise HTTPException(404, str(e))

async def render_call(func, *args):
    """post_call() for functions that render images: waits for any other render to finish first."""
    async with render_lock:
        return await post_call(func, *args)

async def detail_response(name):
    """The post's details plus its running jobs (sends or video renders), so a reloaded page shows their progress."""
    detail = await post_call(pipeline_service.session_detail, name)
    detail["jobs"] = [j for j in send_jobs.values() if j["session"] == name and j["status"] == "running"]
    return detail

@app.get("/api/gemini/models")
async def gemini_models():
    """The models offered on the New post page, with the last used one preselected. Errors are returned, not raised."""
    profile = load_gemini_credentials()
    if not profile.get("gemini_api_key"):
        return {"models": [], "last": None, "error": "No Gemini API key saved. Add one on the Setup page."}
    try:
        models = await run_in_threadpool(list_gemini_models, profile["gemini_api_key"])
    except Exception as e:
        return {"models": [], "last": profile.get("last_used_model"), "error": f"Couldn't list the models: {e}"}
    return {"models": models, "last": profile.get("last_used_model"), "error": None}

@app.post("/api/uploads")
async def upload_media(request: Request):
    """Receives the photo or video chosen for a new post; returns a token that the post is created with.

    The file is the raw request body, written to _workspace/web_uploads/ as it arrives (up to 2 GB), then
    checked by pipeline_service.adopt_upload (photos: readable by Pillow, up to 30 MB; videos: readable by
    ffmpeg, with a still frame and a browser-playable copy made now). Requiring one of these content types
    (not ones a plain HTML form can send) also keeps other sites out.
    """
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith(("image/", "video/", "application/octet-stream")):
        raise HTTPException(415, "Send the photo or video as the request body with an image/* or video/* content type.")
    if int(request.headers.get("content-length") or 0) > pipeline_service.MAX_VIDEO_BYTES:
        raise HTTPException(413, "The file is larger than 2 GB.")

    path = pipeline_service.new_upload_path()
    size = 0
    try:
        with open(path, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > pipeline_service.MAX_VIDEO_BYTES:
                    raise HTTPException(413, "The file is larger than 2 GB.")
                await run_in_threadpool(f.write, chunk)
    except BaseException:
        os.remove(path)
        raise
    return {"token": await post_call(pipeline_service.adopt_upload, path)}

class TelegramPhotoBody(BaseModel):
    chat_id: int
    msg_id: int

@app.post("/api/uploads/telegram")
async def upload_from_telegram(body: TelegramPhotoBody):
    """Downloads a message's photo or video into web_uploads/ and returns a token, like an upload."""
    require_telegram()
    target = pipeline_service.new_upload_path("download")
    path = await telegram_call(telegram.download_source_media(body.chat_id, body.msg_id, target))
    return {"token": await post_call(pipeline_service.adopt_upload, path)}

@app.get("/api/sessions")
async def sessions_list():
    """The Posts tab: the newest posts first."""
    return await post_call(pipeline_service.list_sessions)

class NewPostBody(BaseModel):
    text: str
    image_token: str  # from /api/uploads; a photo or a video
    model: str | None = None  # Gemini model; the last used one when missing

@app.post("/api/sessions")
async def create_post(body: NewPostBody):
    """Translates the text with Gemini and creates the post's session folder with the photo or video."""
    name = await post_call(pipeline_service.create_session, body.text, body.image_token, body.model)
    return {"name": name}

@app.get("/api/sessions/{name}")
async def post_detail(name: str):
    """Everything the post page shows: texts, channels with their images/videos and captions, send log, jobs."""
    return await detail_response(name)

@app.get("/api/sessions/{name}/files/{filename}")
async def post_file(name: str, filename: str):
    """A picture or video from the post's folder (only image and mp4 files directly in it)."""
    path = await post_call(pipeline_service.session_file, name, filename)
    # URLs carry ?v=<modification time>, so a new render gets a new URL
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})

class TextBody(BaseModel):
    headline: str
    body: str

@app.put("/api/sessions/{name}/texts/{lang}")
async def save_post_text(name: str, lang: str, body: TextBody):
    """Saves <lang>.md. Images and captions made from the old text are then reported as outdated."""
    session_dir = await post_call(pipeline_service.session_path, name)
    await post_call(pipeline_service.write_text, session_dir, lang, body.headline, body.body)
    return {"saved": True}

class RenderBody(BaseModel):
    aoi: list[float] | None = None  # area to keep: [left, top, right, bottom] in photo pixels, may go past the edges
    blur: int = pipeline_service.DEFAULT_BLUR  # background blur radius
    mute: bool = False  # video posts: leave the sound out

@app.post("/api/sessions/{name}/render")
async def render_post(name: str, body: RenderBody):
    """Saves the area, blur and mute (web_render.json) and renders every channel's image.

    For a video post the images are stills, and the videos follow as a background job.
    """
    session_dir = await post_call(pipeline_service.session_path, name)
    await post_call(pipeline_service.set_render_options, session_dir, body.aoi, body.blur, body.mute)
    await render_call(pipeline_service.render_channels, session_dir)
    start_video_job(name, session_dir)
    return await detail_response(name)

class VideosBody(BaseModel):
    channels: list[str] | None = None

@app.post("/api/sessions/{name}/videos")
async def render_post_videos(name: str, body: VideosBody):
    """Renders a video post's videos again (all channels, or the given ones), e.g. after one failed."""
    session_dir = await post_call(pipeline_service.session_path, name)
    if not start_video_job(name, session_dir, body.channels):
        raise HTTPException(400, "This post has no video.")
    return await detail_response(name)

class OverrideBody(BaseModel):
    headline: str | None = None
    font_size: int | None = None

@app.put("/api/sessions/{name}/channels/{channel}/override")
async def override_channel(name: str, channel: str, body: OverrideBody):
    """Image-only headline and font size for one channel; an empty body goes back to the text's headline."""
    session_dir = await post_call(pipeline_service.session_path, name)
    await render_call(pipeline_service.set_override, session_dir, channel, body.headline, body.font_size)
    start_video_job(name, session_dir, [channel])
    return await detail_response(name)

@app.post("/api/sessions/{name}/channels/{channel}/shrink")
async def shrink_channel(name: str, channel: str):
    """Shrink font: lowers one channel's headline font size until it fits, re-rendering that channel."""
    session_dir = await post_call(pipeline_service.session_path, name)
    await render_call(pipeline_service.shrink_to_fit, session_dir, channel)
    start_video_job(name, session_dir, [channel])
    return await detail_response(name)

@app.post("/api/sessions/{name}/channels/{channel}/shorten")
async def shorten_channel(name: str, channel: str):
    """Shorten with Gemini: an image-only shorter headline for one channel, re-rendering that channel."""
    session_dir = await post_call(pipeline_service.session_path, name)
    await render_call(pipeline_service.shorten_with_gemini, session_dir, channel)
    start_video_job(name, session_dir, [channel])
    return await detail_response(name)

class CaptionBody(BaseModel):
    text: str

@app.put("/api/sessions/{name}/captions/{channel}")
async def save_post_caption(name: str, channel: str, body: CaptionBody):
    """Saves an edited caption (<channel>_caption.txt, Telegram HTML)."""
    session_dir = await post_call(pipeline_service.session_path, name)
    await post_call(pipeline_service.save_caption, session_dir, channel, body.text)
    return {"saved": True}

@app.post("/api/sessions/{name}/captions/{channel}/rebuild")
async def rebuild_post_caption(name: str, channel: str):
    """Rebuild from text: recreates a caption from the channel's <lang>.md and template, discarding edits."""
    session_dir = await post_call(pipeline_service.session_path, name)
    await post_call(pipeline_service.rebuild_caption, session_dir, channel)
    return await detail_response(name)

class SendBody(BaseModel):
    kind: str  # "previews" (to the review channel) or "published" (to the live channels)
    channels: list[str]

def job_update(job):
    """Sends the job's current state to every open page as a "job" event."""
    telegram.push({"type": "job", "job": job})

def running_job(name, kinds):
    """The post's running job of one of these kinds, or None."""
    return next((j for j in send_jobs.values() if j["session"] == name and j["kind"] in kinds and j["status"] == "running"), None)

def add_job(job):
    """Registers a job, forgetting the oldest ones beyond MAX_KEPT_JOBS (dicts keep insertion order)."""
    send_jobs[job["id"]] = job
    for old_id in list(send_jobs)[:-MAX_KEPT_JOBS]:
        send_jobs.pop(old_id)

def start_video_job(name, session_dir, channels=None):
    """Starts rendering a video post's videos (all channels by default) in the background.

    Called after every change that re-renders stills (render, headline override, shrink, shorten),
    so the videos always follow their stills. Progress arrives as "job" events. A render already
    running for the post is stopped and marked "replaced"; the new job also renders the channels the
    old one hadn't finished, so none is left out. Channels render in channels.json order. Returns
    the job, or None for a photo post.
    """
    if not pipeline_service.find_raw_video(session_dir):
        return None
    config_order = list(load_channels_config().get("channels", {}))
    wanted = set(config_order if channels is None else channels)
    previous = running_job(name, ("videos",))
    if previous:
        previous["cancelled"] = True
        previous["status"] = "replaced"
        job_update(previous)
        wanted |= {c for c in previous["channels"] if c not in previous["results"]}

    job = {"id": os.urandom(6).hex(), "session": name, "kind": "videos",
           "channels": [c for c in config_order if c in wanted], "status": "running",
           "results": {}, "current": None, "progress": 0, "error": None, "cancelled": False}
    add_job(job)
    asyncio.create_task(run_video_job(job, session_dir))
    return job

async def run_video_job(job, session_dir):
    """Renders the job's videos in a worker thread once no other video job is running.

    "current"/"progress" show the channel being encoded; results[channel] = {"ok", "error"} as each ends.
    A job cancelled by a newer one stops at the next progress callback (ffmpeg is killed and its partial
    file removed) or, if it was still waiting for the lock, doesn't start.
    """
    loop = asyncio.get_running_loop()

    def set_progress(channel, fraction):
        job["current"], job["progress"] = channel, round(fraction, 3)
        job_update(job)

    def set_done(channel, error):
        job["results"][channel] = {"ok": error is None, "error": error}
        job["current"], job["progress"] = None, 0
        job_update(job)

    # Called from the worker thread: the job is only changed on the event loop's thread
    def on_progress(channel, fraction):
        if job["cancelled"]:
            raise pipeline_service.RenderCancelled()
        loop.call_soon_threadsafe(set_progress, channel, fraction)

    def on_done(channel, error):
        loop.call_soon_threadsafe(set_done, channel, error)

    async with video_lock:
        if job["cancelled"]:
            return
        try:
            await run_in_threadpool(pipeline_service.render_videos, session_dir, job["channels"], on_progress, on_done)
            job["status"] = "done"
        except pipeline_service.RenderCancelled:
            return  # replaced by a newer job, which reports from here on
        except Exception as e:
            job["status"], job["error"] = "failed", str(e)
    # Lets the last on_done callbacks run before the final update
    await asyncio.sleep(0)
    job_update(job)

async def run_send_job(job, session_dir):
    """Sends previews or live posts channel by channel, recording each in web_publish_log.json.

    After publishing, the published channels' previews are deleted from the review channel. A channel
    whose send failed gets {"ok": False} and the others continue; an error that stops the whole send
    fails the job (and its previews stay).
    """
    config = load_channels_config()

    def on_sent(channel, message):
        pipeline_service.record_sent(session_dir, job["kind"], channel, message)
        job["results"][channel] = ({"ok": True, "chat_id": message.chat_id, "msg_id": message.id}
                                   if message else {"ok": False})
        job_update(job)

    try:
        if job["kind"] == "previews":
            await publisher.send_previews(telegram.client, job["target"], session_dir, job["channels"], on_sent)
        else:
            await publisher.publish_live(telegram.client, config.get("channels", {}), session_dir, job["channels"], on_sent)
            await remove_published_previews(job, session_dir)
        job["status"] = "done"
    except Exception as e:
        job["status"], job["error"] = "failed", str(e)
    job_update(job)

async def remove_published_previews(job, session_dir):
    """Deletes the previews of the channels that were just published from the review channel.

    Only messages VTP recorded as its own previews are deleted. A failure (e.g. no right to delete
    in the review channel) is reported on the job; the publishing itself has succeeded.
    """
    published = [c for c, r in job["results"].items() if r.get("ok")]
    previews = await run_in_threadpool(pipeline_service.previews_of, session_dir, published)
    by_chat = {}
    for preview in previews:
        by_chat.setdefault(preview["chat_id"], []).append(preview)

    deleted, errors = [], []
    for chat_id, chat_previews in by_chat.items():
        try:
            await telegram.delete_messages(chat_id, [p["msg_id"] for p in chat_previews])
            deleted += chat_previews
        except Exception as e:
            errors.append(str(e))
    if deleted:
        await run_in_threadpool(pipeline_service.forget_previews, session_dir, deleted)
    job["previews_removed"] = len(deleted)
    if errors:
        job["cleanup_error"] = f"{len(previews) - len(deleted)} preview(s) couldn't be deleted from the review channel: {'; '.join(errors)}"

@app.post("/api/sessions/{name}/send")
async def send_post(name: str, body: SendBody):
    """Starts sending previews or live posts; progress arrives as "job" events on /api/events.

    Refused while the post is already being sent or its videos are rendering. Missing captions are
    created from the texts first. Sends go a few seconds apart (publisher) to stay within Telegram's limits.
    """
    require_telegram()
    session_dir = await post_call(pipeline_service.session_path, name)
    config = load_channels_config()
    unknown = [c for c in body.channels if c not in config.get("channels", {})]
    if body.kind not in SEND_KINDS or unknown or not body.channels:
        raise HTTPException(400, "Choose at least one configured channel." + (f" Unknown: {', '.join(unknown)}" if unknown else ""))
    if running_job(name, SEND_KINDS):
        raise HTTPException(409, "This post is already being sent. Wait for it to finish.")
    if running_job(name, ("videos",)):
        raise HTTPException(409, "The videos are still rendering. Send once they're done.")

    target = None
    if body.kind == "previews":
        target = parse_target(config.get("catch_all_channel"))
        if not target:
            raise HTTPException(400, "No review channel set (catch_all_channel in channels.json).")

    await post_call(pipeline_service.ensure_captions, session_dir)
    job_id = os.urandom(6).hex()
    job = {"id": job_id, "session": name, "kind": body.kind, "channels": body.channels, "target": target,
           "status": "running", "results": {}, "error": None}
    add_job(job)
    asyncio.create_task(run_send_job(job, session_dir))
    return job

@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
    """A job's current state, for when a live update may have been missed."""
    if job_id not in send_jobs:
        raise HTTPException(404, "No such job.")
    return send_jobs[job_id]

# ==========================================
# ENTRY POINT
# ==========================================
def open_browser(url):
    """Opens the UI in the default browser; on Termux this is Android's browser."""
    if shutil.which("termux-open-url"):
        subprocess.Popen(["termux-open-url", url])
    else:
        webbrowser.open(url)

def main():
    """Parses --port and --no-browser, opens the browser and runs the server until Ctrl+C."""
    parser = argparse.ArgumentParser(description="VTP web interface")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true", help="don't open the browser automatically")
    args = parser.parse_args()

    url = f"http://127.0.0.1:{args.port}/"
    print("========================================================")
    print("  VTP WEB INTERFACE")
    print("========================================================")
    print(f"[OK] Open {url} in a browser on this device.")
    print("[i] Press Ctrl+C to stop the server.")

    if not args.no_browser:
        # Gives uvicorn a moment to start listening first
        browser_timer = threading.Timer(1.5, open_browser, args=(url,))
        browser_timer.daemon = True
        browser_timer.start()

    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning",
                timeout_graceful_shutdown=2)

if __name__ == "__main__":
    main()
