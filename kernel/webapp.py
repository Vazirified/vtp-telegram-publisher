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
from publisher import parse_target
from telegram_service import TelegramService, clean_web_cache

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

WEB_DIR = os.path.join(PROJECT_ROOT, "kernel", "web")
FONTS_DIR = os.path.join(PROJECT_ROOT, "_config", "fonts")
DEFAULT_PORT = 8765

# The server only listens on 127.0.0.1. Checking the Host header as well stops other
# websites from reaching it through DNS rebinding (a domain that resolves to 127.0.0.1).
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)

telegram = TelegramService()

@asynccontextmanager
async def lifespan(app):
    clean_web_cache()
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
@app.get("/")
async def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))

app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

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
