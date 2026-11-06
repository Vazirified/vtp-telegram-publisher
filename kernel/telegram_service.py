"""Telegram access for the web interface (webapp.py); the terminal tools don't use this module.

TelegramService keeps one Telethon client (from auth_manager) connected while the web server
runs. It handles the Setup page's login (API ID/hash, phone, code, two-step password), lists
chats and messages as plain dicts for the page, reacts, deletes VTP's own previews, downloads
source photos/videos for new posts, and pushes live updates (new, edited and deleted messages,
reaction changes) to every open browser tab through queues that webapp streams as
server-sent events. Reading never marks messages as read.

Images the page shows (photos, thumbnails, profile pictures, custom emoji) are downloaded once
into _workspace/web_cache/ and deleted after CACHE_MAX_AGE_DAYS (clean_web_cache, at start-up).
"""
import os
import glob
import json
import time
import asyncio

from telethon import events, functions, types, utils
from telethon.errors import (
    SessionPasswordNeededError, PhoneNumberInvalidError, PhoneCodeInvalidError,
    PhoneCodeExpiredError, PasswordHashInvalidError, FloodWaitError, RPCError,
)
from telethon.extensions import html as telegram_html
from telethon.tl.types import MessageService

import auth_manager
from common import WORKSPACE_DIR, CREDENTIALS_DIR

# Photos, thumbnails, profile pictures and custom emoji shown by the web viewer
WEB_CACHE_DIR = os.path.join(WORKSPACE_DIR, "web_cache")
CACHE_MAX_AGE_DAYS = 7
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")

# ==========================================
# MESSAGES AS DICTS
# ==========================================
# Chats are identified by Telethon's "marked" IDs (utils.get_peer_id): users positive,
# groups negative, channels -100...; numeric chat IDs in channels.json have the same form.

def make_preview(text, limit=80):
    """Flattens text onto one line and cuts it to `limit` characters with an ellipsis."""
    preview = " ".join(text.split())
    if len(preview) > limit:
        preview = preview[:limit - 3] + "..."
    return preview

def media_label(msg):
    """Short description of a message's media, or None if it has none."""
    if msg.photo: return "Photo"
    if msg.gif: return "GIF"
    if msg.video: return "Video"
    if msg.voice: return "Voice message"
    if msg.audio: return "Audio"
    if is_pack_sticker(msg): return "Sticker"
    if msg.poll: return "Poll"
    if msg.geo: return "Location"
    if msg.contact: return "Contact"
    if msg.document: return "File"
    return None

def has_preview_image(msg):
    """True if the viewer can show an image for this message (photo, thumbnail or link preview)."""
    if msg.photo:
        return True
    if msg.document and msg.document.thumbs:
        return True
    return bool(msg.web_preview and msg.web_preview.photo)

def is_pack_sticker(msg):
    """True for a sticker from a sticker pack.

    Telegram also marks .webp files people send as stickers, but those belong to no pack
    (InputStickerSetEmpty); they count as photos, so they can be a post's raw image.
    """
    sticker = msg.sticker
    if not sticker:
        return False
    attribute = next(a for a in sticker.attributes if isinstance(a, types.DocumentAttributeSticker))
    return not isinstance(attribute.stickerset, types.InputStickerSetEmpty)

def is_source_photo(msg):
    """True if the message holds a full photo (or image file) that can be a post's raw image.

    Whether VTP can read the format is checked after download (pipeline_service.adopt_upload).
    """
    if msg.photo:
        return True
    return bool(msg.document and not is_pack_sticker(msg) and msg.file and (msg.file.mime_type or "").startswith("image/"))

def is_source_video(msg):
    """True if the message holds a video (incl. Telegram "GIFs" and round videos) that can be a post's video."""
    return bool(msg.document and not is_pack_sticker(msg) and msg.file and (msg.file.mime_type or "").startswith("video/"))

def largest_size(sizes):
    """[width, height] of the largest photo size or thumbnail that has dimensions, or None."""
    sized = [s for s in (sizes or []) if getattr(s, "w", None) and getattr(s, "h", None)]
    if not sized:
        return None
    best = max(sized, key=lambda s: s.w * s.h)
    return [best.w, best.h]

def preview_image_size(msg):
    """Dimensions of the image the viewer shows, so the page can reserve its space before it loads."""
    if msg.photo:
        return largest_size(msg.photo.sizes)
    if msg.document and msg.document.thumbs:
        return largest_size(msg.document.thumbs)
    if msg.web_preview and msg.web_preview.photo:
        return largest_size(msg.web_preview.photo.sizes)
    return None

def profile_photo_id(entity):
    """ID of the chat's or user's current profile picture, or None. Changes when the picture changes."""
    photo_id = getattr(getattr(entity, "photo", None), "photo_id", None)
    return str(photo_id) if photo_id else None

def reaction_to_dict(reaction):
    """{"emoji"} for normal reactions, {"custom_emoji_id"} for custom emoji, {"paid"} for star reactions."""
    if isinstance(reaction, types.ReactionCustomEmoji):
        return {"custom_emoji_id": str(reaction.document_id)}
    if isinstance(reaction, types.ReactionPaid):
        return {"paid": True}
    return {"emoji": getattr(reaction, "emoticon", None) or "?"}

def reactor_peers(msg):
    """Marked IDs of the users and chats in a message's recent reactions."""
    reactions = getattr(msg, "reactions", None)
    if not reactions or not reactions.recent_reactions:
        return set()
    return {utils.get_peer_id(r.peer_id) for r in reactions.recent_reactions}

def reactions_to_dict(reactions, names):
    """Reaction counts plus who reacted recently. `names` maps marked peer IDs to display names.

    Telegram only lists who reacted in groups and private chats; in channels reactions are anonymous.
    """
    if not reactions or not reactions.results:
        return None
    return {
        "results": [
            dict(reaction_to_dict(r.reaction), count=r.count, mine=r.chosen_order is not None)
            for r in reactions.results
        ],
        "recent": [
            dict(reaction_to_dict(r.reaction), name=names.get(utils.get_peer_id(r.peer_id), "Someone"),
                 unread=bool(r.unread), mine=bool(r.my))
            for r in (reactions.recent_reactions or [])
        ],
        "can_see_list": bool(reactions.can_see_list),
    }

def message_to_dict(msg, names=None):
    """The fields of a Telethon message that the web viewer shows. Service messages get only id, date and kind."""
    if isinstance(msg, MessageService):
        action = type(msg.action).__name__.replace("MessageAction", "")
        return {"id": msg.id, "date": msg.date.isoformat(), "service": action}

    sender = msg.post_author or ""
    if not sender and msg.sender:
        sender = utils.get_display_name(msg.sender)

    return {
        "id": msg.id,
        "date": msg.date.isoformat(),
        "edit_date": msg.edit_date.isoformat() if msg.edit_date else None,
        "out": bool(msg.out),
        "sender": sender,
        # Telegram HTML; the browser rebuilds it from an allowlist of tags before showing it
        "html": telegram_html.unparse(msg.message, msg.entities) if msg.message else "",
        # Plain text, used as the source text when a post is started from selected messages
        "text": msg.message or "",
        "source_photo": is_source_photo(msg),
        "source_video": is_source_video(msg),
        "media": media_label(msg),
        "file_name": msg.file.name if msg.document and msg.file else None,
        "has_image": has_preview_image(msg),
        "image_size": preview_image_size(msg),
        "grouped_id": str(msg.grouped_id) if msg.grouped_id else None,
        "reply_to": msg.reply_to_msg_id,
        "views": msg.views,
        "forwards": msg.forwards,
        "reactions": reactions_to_dict(msg.reactions, names or {}),
    }

def chat_kind(entity):
    """'user', 'group' or 'channel'."""
    if getattr(entity, "broadcast", False):
        return "channel"
    if getattr(entity, "megagroup", False) or type(entity).__name__ in ("Chat", "ChatForbidden"):
        return "group"
    return "user"

# ==========================================
# SERVICE
# ==========================================
class TelegramService:
    """One Telegram client shared by the web server: login, browsing, reacting and live updates.

    Methods are coroutines run on the server's event loop. Errors the user can act on are raised
    as ValueError with a readable message (webapp turns them into HTTP 400).
    """

    def __init__(self):
        self.client = None
        # connecting | no_credentials | logged_out | ready | error
        self.state = "connecting"
        self.error = None
        self.me = None
        self.login_phone = None
        self.login_step = None  # "code" or "password" while logging in
        self.subscribers = set()  # one asyncio.Queue per open /api/events stream
        self.download_locks = {}  # cache key -> lock while that file downloads
        self.peer_names = {}  # marked peer ID -> display name, for reaction lists
        self.reaction_rules = {}  # marked chat ID -> which reactions the chat allows
        self.standard_reaction_list = None  # Telegram's standard emoji reactions, loaded once

    # ---------------------------------------------------------------- lifecycle
    async def start(self):
        """Connects with the saved session. Never raises; failures are reported through status()."""
        self.state, self.error = "connecting", None
        if not os.path.exists(auth_manager.CREDENTIALS_FILE):
            self.state = "no_credentials"
            print("[!] Telegram API credentials missing. Add them on the Setup page.")
            return

        client = auth_manager.get_client()
        if not client:
            self.state = "error"
            self.error = "Could not read _credentials/telegram_api.json (see the terminal for details)."
            return

        try:
            await client.connect()
            authorized = await client.is_user_authorized()
        except Exception as e:
            self.state = "error"
            self.error = f"Could not connect to Telegram: {e}"
            if "database is locked" in str(e):
                self.error += (" The Telegram session is in use by another VTP window"
                               " (run.bat/run.sh, publisher.py or inspect-emoji.py). Close it and restart.")
            print(f"[ERROR] {self.error}")
            return

        self.client = client
        if authorized:
            await self.on_authorized()
        else:
            self.state = "logged_out"
            print("[!] Telegram is not logged in. Log in on the Setup page.")

    async def stop(self):
        if self.client:
            await self.client.disconnect()

    async def restart(self):
        """Disconnects and connects again, e.g. after another program released the session file."""
        await self.stop()
        self.client = self.me = None
        self.login_phone = self.login_step = None
        await self.start()

    async def on_authorized(self):
        """After login (or connecting with a logged-in session): registers the live update handlers."""
        self.me = await self.client.get_me()
        self.login_phone = self.login_step = None
        for event_type in (events.NewMessage(), events.MessageEdited(), events.MessageDeleted()):
            self.client.add_event_handler(self.broadcast_update, event_type)
        # Reaction changes are their own update type; the message events above don't include them
        self.client.add_event_handler(self.broadcast_reactions, events.Raw(types.UpdateMessageReactions))
        # Chats you read in another Telegram app, so the unread counts in the chat list follow
        self.client.add_event_handler(self.broadcast_read, events.MessageRead(inbox=True))
        self.state = "ready"
        print(f"[OK] Telegram logged in as {utils.get_display_name(self.me)}.")
        # Loads recent chats so numeric IDs from channels.json can be resolved
        asyncio.create_task(self.warm_up())

    async def warm_up(self):
        try:
            await self.client.get_dialogs(limit=100)
        except Exception as e:
            print(f"  [!] Chat list warm-up skipped: {e}")

    def status(self):
        """Connection state, error, logged-in account and login step, for the page's Setup tab and status dot."""
        me = None
        if self.me:
            me = {"name": utils.get_display_name(self.me), "username": self.me.username}
        return {"state": self.state, "error": self.error, "me": me,
                "login_step": self.login_step, "login_phone": self.login_phone}

    # ---------------------------------------------------------------- setup and login
    async def save_api_credentials(self, api_id, api_hash):
        """Writes _credentials/telegram_api.json and connects with it."""
        os.makedirs(CREDENTIALS_DIR, exist_ok=True)
        with open(auth_manager.CREDENTIALS_FILE, "w", encoding="utf-8") as f:
            json.dump({"api_id": api_id, "api_hash": api_hash}, f, indent=2)
        await self.restart()

    # Login runs in steps driven by the Setup page: send_code -> submit_code -> (submit_password)
    async def send_code(self, phone):
        try:
            await self.client.send_code_request(phone)
        except PhoneNumberInvalidError:
            raise ValueError("Telegram doesn't accept this phone number. Include the country code, e.g. +98...")
        except FloodWaitError as e:
            raise ValueError(f"Too many attempts. Telegram asks to wait {e.seconds} seconds.")
        self.login_phone = phone
        self.login_step = "code"

    async def submit_code(self, code):
        try:
            await self.client.sign_in(phone=self.login_phone, code=code)
        except SessionPasswordNeededError:
            self.login_step = "password"
            return
        except (PhoneCodeInvalidError, PhoneCodeExpiredError):
            raise ValueError("The code is wrong or has expired. Request a new one if needed.")
        await self.on_authorized()

    async def submit_password(self, password):
        try:
            await self.client.sign_in(password=password)
        except PasswordHashInvalidError:
            raise ValueError("Wrong two-step verification password.")
        await self.on_authorized()

    # ---------------------------------------------------------------- browsing
    async def list_dialogs(self, offset_date=None, limit=30):
        """The chat list, newest first; offset_date continues after the last chat of the previous page."""
        kwargs = {"limit": limit}
        if offset_date:
            kwargs["offset_date"] = offset_date

        dialogs = []
        async for dialog in self.client.iter_dialogs(**kwargs):
            preview = ""
            if dialog.message:
                if isinstance(dialog.message, MessageService):
                    preview = "Service message"
                else:
                    preview = make_preview(dialog.message.message or "") or media_label(dialog.message) or ""
            dialogs.append({
                "id": dialog.id,
                "name": dialog.name or "Unknown Chat",
                "kind": chat_kind(dialog.entity),
                "photo": profile_photo_id(dialog.entity),
                "unread": dialog.unread_count,
                "read_up_to": getattr(dialog.dialog, "read_inbox_max_id", 0),  # newest message you've read
                # Reactions to your messages that you haven't seen yet
                "unread_reactions": getattr(dialog.dialog, "unread_reactions_count", 0),
                "pinned": dialog.pinned,
                "date": dialog.date.isoformat() if dialog.date else None,
                "preview": preview,
            })
        return dialogs

    async def chat_info(self, chat_id):
        """Name, kind, profile picture and username of one chat (a marked ID, or a @username)."""
        entity = await self.client.get_entity(chat_id)
        is_self = self.me and getattr(entity, "id", None) == self.me.id
        return {
            "id": utils.get_peer_id(entity),
            "name": "Saved Messages" if is_self else utils.get_display_name(entity),
            "kind": chat_kind(entity),
            "photo": profile_photo_id(entity),
            "username": getattr(entity, "username", None),
        }

    async def resolve_names(self, peer_ids):
        """Fills self.peer_names for the given marked IDs, in one request where possible."""
        missing = [p for p in peer_ids if p not in self.peer_names]
        if not missing:
            return self.peer_names
        try:
            entities = await self.client.get_entity(missing)
        except Exception:
            # One unknown peer fails the whole batch; fall back to one request each
            entities = []
            for peer_id in missing:
                try:
                    entities.append(await self.client.get_entity(peer_id))
                except Exception:
                    pass
        for entity in entities:
            self.peer_names[utils.get_peer_id(entity)] = utils.get_display_name(entity)
        return self.peer_names

    async def messages_to_dicts(self, messages):
        """message_to_dict for each message, with the names of recent reactors looked up first."""
        peers = set()
        for msg in messages:
            peers |= reactor_peers(msg)
        names = await self.resolve_names(peers) if peers else {}
        return [message_to_dict(msg, names) for msg in messages]

    async def list_messages(self, chat_id, offset_id=0, limit=30):
        """Newest first, older than offset_id when given. Reading does not mark messages as read."""
        kwargs = {"limit": limit}
        if offset_id:
            kwargs["offset_id"] = offset_id
        messages = [msg async for msg in self.client.iter_messages(chat_id, **kwargs)]
        return await self.messages_to_dicts(messages)

    async def get_message(self, chat_id, msg_id):
        """One message, e.g. to refresh it after its reactions changed. None if it was deleted."""
        msg = await self.client.get_messages(chat_id, ids=msg_id)
        if not msg:
            return None
        return (await self.messages_to_dicts([msg]))[0]

    async def mark_read(self, chat_id, max_id=0, reactions=False):
        """Marks a chat as read up to max_id (0 leaves the messages unread) and, with reactions, its new
        reactions to your messages as seen. Senders see their messages as read, as with the Telegram apps."""
        if reactions:
            # Not send_read_acknowledge(clear_reactions=True): without a max_id it also reads every message
            await self.client(functions.messages.ReadReactionsRequest(await self.client.get_input_entity(chat_id)))
        if max_id:
            await self.client.send_read_acknowledge(chat_id, max_id=max_id)

    async def list_reactors(self, chat_id, msg_id):
        """Everyone who reacted to a message, newest first. Telegram refuses this in broadcast channels."""
        peer = await self.client.get_input_entity(chat_id)
        result = await self.client(functions.messages.GetMessageReactionsListRequest(peer=peer, id=msg_id, limit=100))
        entities = {utils.get_peer_id(e): e for e in list(result.users) + list(result.chats)}
        reactors = []
        for r in result.reactions:
            entity = entities.get(utils.get_peer_id(r.peer_id))
            reactors.append(dict(reaction_to_dict(r.reaction),
                                 name=utils.get_display_name(entity) if entity else "Someone",
                                 date=r.date.isoformat(), unread=bool(r.unread), mine=bool(r.my)))
        return reactors

    # ---------------------------------------------------------------- reacting
    async def chat_reaction_rules(self, chat_id):
        """("all" | "some" | "none", custom emoji allowed, [allowed reactions when "some"]), cached per chat."""
        if chat_id in self.reaction_rules:
            return self.reaction_rules[chat_id]
        entity = await self.client.get_entity(chat_id)
        if isinstance(entity, types.User):
            rules = ("all", True, [])
        else:
            if isinstance(entity, types.Channel):
                full = await self.client(functions.channels.GetFullChannelRequest(entity))
            else:
                full = await self.client(functions.messages.GetFullChatRequest(entity.id))
            available = full.full_chat.available_reactions
            if isinstance(available, types.ChatReactionsSome):
                rules = ("some", True, [reaction_to_dict(r) for r in available.reactions])
            elif isinstance(available, types.ChatReactionsNone):
                rules = ("none", False, [])
            else:  # ChatReactionsAll, or not set (Telegram's default is all)
                rules = ("all", bool(getattr(available, "allow_custom", False)), [])
        self.reaction_rules[chat_id] = rules
        return rules

    async def standard_reactions(self):
        """Telegram's standard emoji reactions this account may use (Premium-only ones need Premium)."""
        if self.standard_reaction_list is None:
            premium = bool(getattr(self.me, "premium", False))
            result = await self.client(functions.messages.GetAvailableReactionsRequest(hash=0))
            self.standard_reaction_list = [{"emoji": r.reaction} for r in result.reactions
                                           if not r.inactive and (premium or not r.premium)]
        return self.standard_reaction_list

    async def reaction_menu(self, chat_id):
        """What the reaction picker offers in a chat.

        Returns {"allowed": "all" | "some" | "none", "recent": [...], "all": [...]}; "recent" is the
        account's recently used reactions (the same list the Telegram apps show), limited to what
        this chat allows.
        """
        allowed, custom_ok, some = await self.chat_reaction_rules(chat_id)
        if allowed == "none":
            return {"allowed": "none", "recent": [], "all": []}
        premium = bool(getattr(self.me, "premium", False))
        everything = some if allowed == "some" else await self.standard_reactions()

        def usable(reaction):
            if reaction.get("paid"):
                return False
            if reaction.get("custom_emoji_id"):
                return premium and custom_ok and (allowed == "all" or reaction in some)
            return allowed == "all" or reaction in some

        result = await self.client(functions.messages.GetRecentReactionsRequest(limit=30, hash=0))
        recent = [r for r in (reaction_to_dict(x) for x in getattr(result, "reactions", [])) if usable(r)]
        return {"allowed": allowed, "recent": recent[:12], "all": [r for r in everything if usable(r)]}

    async def send_reaction(self, chat_id, msg_id, reactions):
        """Sets your reaction(s) on a message; an empty list removes yours. Returns the updated message."""
        reaction = [types.ReactionCustomEmoji(document_id=int(r["custom_emoji_id"])) if r.get("custom_emoji_id")
                    else types.ReactionEmoji(emoticon=r["emoji"]) for r in reactions]
        peer = await self.client.get_input_entity(chat_id)
        try:
            await self.client(functions.messages.SendReactionRequest(
                peer=peer, msg_id=msg_id, reaction=reaction, add_to_recent=True))
        except RPCError as e:
            if "REACTION_INVALID" in str(e):
                raise ValueError("This chat doesn't allow that reaction.")
            if "REACTIONS_TOO_MANY" in str(e) or "PREMIUM" in str(e):
                raise ValueError("Your account can't add more reactions to this message.")
            raise
        return await self.get_message(chat_id, msg_id)

    async def delete_messages(self, chat_id, msg_ids):
        """Deletes messages for everyone (used for VTP's own previews once a post is published)."""
        await self.client.delete_messages(chat_id, msg_ids, revoke=True)

    async def resolve_shortcuts(self, targets):
        """Resolves [(label, target)] from channels.json to chats the viewer can open.

        A target that can't be found is kept with its error; duplicates (same chat) are dropped.
        """
        shortcuts, seen = [], set()
        for label, target in targets:
            try:
                info = await self.chat_info(target)
            except Exception as e:
                shortcuts.append({"label": label, "chat_id": None, "name": str(target), "photo": None, "error": str(e)})
                continue
            if info["id"] in seen:
                continue
            seen.add(info["id"])
            shortcuts.append({"label": label, "chat_id": info["id"], "name": info["name"],
                              "photo": info["photo"], "error": None})
        return shortcuts

    # ---------------------------------------------------------------- images
    async def cached_download(self, key, download):
        """Returns the cached file for `key`, or calls `await download(path_without_extension)` once.

        The same image is often requested by several <img> tags at once; only one download runs.
        Files the browser can't show as images are deleted and give None. Cached files are
        reused until clean_web_cache removes them.
        """
        pattern = os.path.join(WEB_CACHE_DIR, key + ".*")
        cached = glob.glob(pattern)
        if cached:
            return cached[0]

        lock = self.download_locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                cached = glob.glob(pattern)
                if cached:
                    return cached[0]
                os.makedirs(WEB_CACHE_DIR, exist_ok=True)
                path = await download(os.path.join(WEB_CACHE_DIR, key))
                if path and not str(path).lower().endswith(IMAGE_EXTENSIONS):
                    os.remove(path)  # e.g. an animated sticker the browser can't show
                    return None
                return path
        finally:
            self.download_locks.pop(key, None)

    async def preview_image(self, chat_id, msg_id):
        """The image the viewer shows for a message (photo, thumbnail or link preview), or None."""
        async def download(target):
            msg = await self.client.get_messages(chat_id, ids=msg_id)
            if not msg or not has_preview_image(msg):
                return None
            if msg.photo:
                return await self.client.download_media(msg, file=target)
            if msg.document and msg.document.thumbs:
                return await self.client.download_media(msg, file=target, thumb=-1)
            return await self.client.download_media(msg.web_preview.photo, file=target)

        return await self.cached_download(f"{chat_id}_{msg_id}", download)

    async def profile_photo(self, chat_id, photo_id):
        """The small (160 px) profile picture of a chat or user, or None if it has none.

        photo_id is part of the cache key, so a changed picture is downloaded again.
        """
        async def download(target):
            entity = await self.client.get_entity(chat_id)
            return await self.client.download_profile_photo(entity, file=target, download_big=False)

        return await self.cached_download(f"avatar_{chat_id}_{photo_id}", download)

    async def download_source_media(self, chat_id, msg_id, target):
        """Downloads a message's full photo or video to `target` (Telethon adds the extension) and returns the path."""
        msg = await self.client.get_messages(chat_id, ids=msg_id)
        if not msg or not (is_source_photo(msg) or is_source_video(msg)):
            raise ValueError("This message has no photo or video.")
        path = await self.client.download_media(msg, file=target)
        if not path:
            raise ValueError("Telegram didn't return the file. Try again.")
        return path

    async def custom_emoji_image(self, document_id):
        """A still image of a custom emoji (used for custom emoji reactions), or None."""
        async def download(target):
            documents = await self.client(functions.messages.GetCustomEmojiDocumentsRequest(document_id=[document_id]))
            if not documents:
                return None
            document = documents[0]
            if document.mime_type in ("image/webp", "image/png"):
                return await self.client.download_media(document, file=target)
            if document.thumbs:
                return await self.client.download_media(document, file=target, thumb=-1)
            return None

        return await self.cached_download(f"emoji_{document_id}", download)

    # ---------------------------------------------------------------- live updates
    # Each update only says which chat and messages changed; the page fetches what it needs again.
    def subscribe(self):
        """A queue that receives every update until unsubscribe(); one per browser tab's event stream."""
        queue = asyncio.Queue(maxsize=200)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue):
        self.subscribers.discard(queue)

    def push(self, update):
        """Tells every open browser tab which chat changed, so it can reload what it shows."""
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(update)
            except asyncio.QueueFull:
                pass  # That tab stopped reading; it reloads when it reconnects

    async def broadcast_update(self, event):
        """Telethon handler for new, edited and deleted messages."""
        if isinstance(event, events.MessageDeleted.Event):
            self.push({"type": "deleted", "chat_id": event.chat_id, "ids": event.deleted_ids})
        elif isinstance(event, events.MessageEdited.Event):
            self.push({"type": "edited", "chat_id": event.chat_id, "ids": [event.message.id]})
        else:
            self.push({"type": "new", "chat_id": event.chat_id, "ids": [event.message.id]})

    async def broadcast_reactions(self, update):
        """Telethon handler for UpdateMessageReactions (reaction counts or reactors changed)."""
        self.push({"type": "reactions", "chat_id": utils.get_peer_id(update.peer), "ids": [update.msg_id]})

    async def broadcast_read(self, event):
        """Telethon handler for chats read in another Telegram app (or by this one)."""
        if event.chat_id and not event.contents:  # "contents" events are about mentions and voice notes
            self.push({"type": "read", "chat_id": event.chat_id})

def clean_web_cache():
    """Deletes cached viewer images older than CACHE_MAX_AGE_DAYS (webapp calls it at start-up)."""
    cutoff = time.time() - CACHE_MAX_AGE_DAYS * 86400
    for path in glob.glob(os.path.join(WEB_CACHE_DIR, "*")):
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            pass
