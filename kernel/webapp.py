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

WEB_DIR = os.path.join(PROJECT_ROOT, "kernel", "web")
FONTS_DIR = os.path.join(PROJECT_ROOT, "_config", "fonts")
DEFAULT_PORT = 8765

# The server only listens on 127.0.0.1. Checking the Host header as well stops other
# websites from reaching it through DNS rebinding (a domain that resolves to 127.0.0.1).
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
    "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)

telegram = TelegramService()

@asynccontextmanager
async def lifespan(app):
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
    if telegram.state != "ready":
        raise HTTPException(503, "Telegram is not logged in. Open the Setup page.")

async def telegram_call(coro):
    """Awaits a Telegram request, turning its errors into a readable HTTP error."""
    try:
        return await coro
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Telegram: {e}")

# ==========================================
# PAGE AND STATIC FILES
# ==========================================
# "no-cache" makes the browser check for a newer version on every load (answered with 304 when unchanged);
# without it, browsers kept running old scripts after an update
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
    api_hash = body.api_hash.strip()
    if not re.fullmatch(r"[0-9a-fA-F]{32}", api_hash):
        raise HTTPException(400, "api_hash should be 32 hexadecimal characters, as shown on my.telegram.org.")
    await telegram.save_api_credentials(body.api_id, api_hash)
    return telegram.status()

@app.post("/api/telegram/reconnect")
async def telegram_reconnect():
    await telegram.restart()
    return telegram.status()

class PhoneBody(BaseModel):
    phone: str

class CodeBody(BaseModel):
    code: str

class PasswordBody(BaseModel):
    password: str

def require_login_client():
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
# TELEGRAM VIEWER (READ-ONLY)
# ==========================================
@app.get("/api/telegram/shortcuts")
async def telegram_shortcuts():
    """The review channel and every live channel from channels.json."""
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
    require_telegram()
    offset = datetime.datetime.fromisoformat(offset_date) if offset_date else None
    return await telegram_call(telegram.list_dialogs(offset))

@app.get("/api/telegram/chats/{chat_id}")
async def telegram_chat(chat_id: int):
    require_telegram()
    return await telegram_call(telegram.chat_info(chat_id))

@app.get("/api/telegram/chats/{chat_id}/messages")
async def telegram_messages(chat_id: int, offset_id: int = 0):
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
    require_telegram()
    return await telegram_call(telegram.list_reactors(chat_id, msg_id))

@app.get("/api/telegram/chats/{chat_id}/reaction-menu")
async def telegram_reaction_menu(chat_id: int):
    require_telegram()
    return await telegram_call(telegram.reaction_menu(chat_id))

class ReactionItem(BaseModel):
    emoji: str | None = Field(None, max_length=16)
    custom_emoji_id: str | None = Field(None, pattern=r"^\d{1,20}$")

class ReactionBody(BaseModel):
    reactions: list[ReactionItem] = Field(max_length=3)  # an empty list removes your reaction

@app.post("/api/telegram/chats/{chat_id}/messages/{msg_id}/reaction")
async def telegram_react(chat_id: int, msg_id: int, body: ReactionBody):
    """Reacts to a message as your account (the one action in the viewer that changes Telegram)."""
    require_telegram()
    if any(not (r.emoji or r.custom_emoji_id) for r in body.reactions):
        raise HTTPException(400, "Each reaction needs an emoji or a custom emoji ID.")
    reactions = [r.model_dump(exclude_none=True) for r in body.reactions]
    return await telegram_call(telegram.send_reaction(chat_id, msg_id, reactions))

def image_response(path, missing_message):
    if not path or not os.path.exists(path):
        raise HTTPException(404, missing_message)
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})

@app.get("/api/telegram/media/{chat_id}/{msg_id}")
async def telegram_media(chat_id: int, msg_id: int):
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
    """Server-sent events: one line per new, edited or deleted Telegram message."""
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
# Rendering writes the session's image files; one render at a time avoids two writers
render_lock = asyncio.Lock()
# Sending previews or live posts runs in the background: job ID -> state
send_jobs = {}
MAX_KEPT_JOBS = 50

async def post_call(func, *args, **kwargs):
    """Runs a pipeline_service function in a worker thread, turning its errors into HTTP errors."""
    try:
        return await run_in_threadpool(func, *args, **kwargs)
    except PostError as e:
        raise HTTPException(400, str(e))
    except PostNotFound as e:
        raise HTTPException(404, str(e))

async def render_call(func, *args):
    async with render_lock:
        return await post_call(func, *args)

async def detail_response(name):
    """The post's details plus any send still running for it (e.g. after the page was reloaded)."""
    detail = await post_call(pipeline_service.session_detail, name)
    detail["jobs"] = [j for j in send_jobs.values() if j["session"] == name and j["status"] == "running"]
    return detail

@app.get("/api/gemini/models")
async def gemini_models():
    profile = load_gemini_credentials()
    if not profile.get("gemini_api_key"):
        return {"models": [], "last": None, "error": "No Gemini API key saved. Add one on the Setup page."}
    try:
        models = await run_in_threadpool(list_gemini_models, profile["gemini_api_key"])
    except Exception as e:
        return {"models": [], "last": profile.get("last_used_model"), "error": f"Couldn't list the models: {e}"}
    return {"models": models, "last": profile.get("last_used_model"), "error": None}

@app.post("/api/uploads")
async def upload_photo(request: Request):
    """The photo is the raw request body. Requiring an image content type also keeps other sites out."""
    if not request.headers.get("content-type", "").startswith("image/"):
        raise HTTPException(415, "Send the photo as the request body with an image/* content type.")
    if int(request.headers.get("content-length") or 0) > pipeline_service.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "The photo is larger than 30 MB.")
    data = await request.body()
    return {"token": await post_call(pipeline_service.save_upload, data)}

class TelegramPhotoBody(BaseModel):
    chat_id: int
    msg_id: int

@app.post("/api/uploads/telegram")
async def upload_from_telegram(body: TelegramPhotoBody):
    require_telegram()
    path = await telegram_call(telegram.download_source_photo(body.chat_id, body.msg_id, pipeline_service.new_download_path()))
    return {"token": await post_call(pipeline_service.adopt_download, path)}

@app.get("/api/sessions")
async def sessions_list():
    return await post_call(pipeline_service.list_sessions)

class NewPostBody(BaseModel):
    text: str
    image_token: str
    model: str | None = None

@app.post("/api/sessions")
async def create_post(body: NewPostBody):
    name = await post_call(pipeline_service.create_session, body.text, body.image_token, body.model)
    return {"name": name}

@app.get("/api/sessions/{name}")
async def post_detail(name: str):
    return await detail_response(name)

@app.get("/api/sessions/{name}/files/{filename}")
async def post_file(name: str, filename: str):
    path = await post_call(pipeline_service.session_file, name, filename)
    # URLs carry ?v=<modification time>, so a new render gets a new URL
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})

class TextBody(BaseModel):
    headline: str
    body: str

@app.put("/api/sessions/{name}/texts/{lang}")
async def save_post_text(name: str, lang: str, body: TextBody):
    session_dir = await post_call(pipeline_service.session_path, name)
    await post_call(pipeline_service.write_text, session_dir, lang, body.headline, body.body)
    return {"saved": True}

class RenderBody(BaseModel):
    aoi: list[float] | None = None
    blur: int = pipeline_service.DEFAULT_BLUR

@app.post("/api/sessions/{name}/render")
async def render_post(name: str, body: RenderBody):
    session_dir = await post_call(pipeline_service.session_path, name)
    await post_call(pipeline_service.set_render_options, session_dir, body.aoi, body.blur)
    await render_call(pipeline_service.render_channels, session_dir)
    return await detail_response(name)

class OverrideBody(BaseModel):
    headline: str | None = None
    font_size: int | None = None

@app.put("/api/sessions/{name}/channels/{channel}/override")
async def override_channel(name: str, channel: str, body: OverrideBody):
    """Image-only headline and font size for one channel; an empty body goes back to the text's headline."""
    session_dir = await post_call(pipeline_service.session_path, name)
    await render_call(pipeline_service.set_override, session_dir, channel, body.headline, body.font_size)
    return await detail_response(name)

@app.post("/api/sessions/{name}/channels/{channel}/shrink")
async def shrink_channel(name: str, channel: str):
    session_dir = await post_call(pipeline_service.session_path, name)
    await render_call(pipeline_service.shrink_to_fit, session_dir, channel)
    return await detail_response(name)

@app.post("/api/sessions/{name}/channels/{channel}/shorten")
async def shorten_channel(name: str, channel: str):
    session_dir = await post_call(pipeline_service.session_path, name)
    await render_call(pipeline_service.shorten_with_gemini, session_dir, channel)
    return await detail_response(name)

class CaptionBody(BaseModel):
    text: str

@app.put("/api/sessions/{name}/captions/{channel}")
async def save_post_caption(name: str, channel: str, body: CaptionBody):
    session_dir = await post_call(pipeline_service.session_path, name)
    await post_call(pipeline_service.save_caption, session_dir, channel, body.text)
    return {"saved": True}

@app.post("/api/sessions/{name}/captions/{channel}/rebuild")
async def rebuild_post_caption(name: str, channel: str):
    session_dir = await post_call(pipeline_service.session_path, name)
    await post_call(pipeline_service.rebuild_caption, session_dir, channel)
    return await detail_response(name)

class SendBody(BaseModel):
    kind: str  # "previews" (to the review channel) or "published" (to the live channels)
    channels: list[str]

def job_update(job):
    telegram.push({"type": "job", "job": job})

async def run_send_job(job, session_dir):
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
    """Starts sending previews or live posts; progress arrives as "job" events on /api/events."""
    require_telegram()
    session_dir = await post_call(pipeline_service.session_path, name)
    config = load_channels_config()
    unknown = [c for c in body.channels if c not in config.get("channels", {})]
    if body.kind not in ("previews", "published") or unknown or not body.channels:
        raise HTTPException(400, "Choose at least one configured channel." + (f" Unknown: {', '.join(unknown)}" if unknown else ""))
    if any(j["session"] == name and j["status"] == "running" for j in send_jobs.values()):
        raise HTTPException(409, "This post is already being sent. Wait for it to finish.")

    target = None
    if body.kind == "previews":
        target = parse_target(config.get("catch_all_channel"))
        if not target:
            raise HTTPException(400, "No review channel set (catch_all_channel in channels.json).")

    await post_call(pipeline_service.ensure_captions, session_dir)
    job_id = os.urandom(6).hex()
    job = {"id": job_id, "session": name, "kind": body.kind, "channels": body.channels, "target": target,
           "status": "running", "results": {}, "error": None}
    send_jobs[job_id] = job
    for old_id in list(send_jobs)[:-MAX_KEPT_JOBS]:
        send_jobs.pop(old_id)
    asyncio.create_task(run_send_job(job, session_dir))
    return job

@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
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
