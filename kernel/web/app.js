"use strict";

// ==========================================
// HELPERS
// ==========================================

/** Fetches JSON from the server. `json` is sent as a POST body. Errors carry the server's message. */
async function api(path, { json, ...init } = {}) {
  if (json !== undefined) {
    init.method = init.method || "POST";
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(json);
  }
  const response = await fetch(path, init);
  let data = null;
  try { data = await response.json(); } catch { /* empty or non-JSON body */ }
  if (!response.ok) {
    throw new Error(errorText(data) || `${response.status} ${response.statusText}`);
  }
  return data;
}

function errorText(data) {
  if (!data) return "";
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) return data.detail.map((d) => d.msg).join("; ");
  return "";
}

/** Creates an element. Props starting with "on" become event listeners. */
function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : String(child));
  }
  return el;
}

const timeFormat = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });
const dayFormat = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" });
const shortDayFormat = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });
const compactNumber = new Intl.NumberFormat(undefined, { notation: "compact" });

function listTime(iso) {
  const date = new Date(iso);
  return date.toDateString() === new Date().toDateString() ? timeFormat.format(date) : shortDayFormat.format(date);
}

/** Profile picture over coloured initials; the initials stay visible if there is no picture. */
function avatar(name, id, photo, size = "") {
  const initials = (name || "?").trim().split(/\s+/).slice(0, 2).map((w) => [...w][0] || "").join("");
  const el = h("span", { class: `avatar ${size}`, "aria-hidden": "true" }, initials.toUpperCase() || "?");
  el.style.background = `hsl(${Math.abs(Number(id) || 0) % 360} 45% 42%)`;
  if (id && photo) {
    const img = h("img", { src: `/api/telegram/avatar/${id}/${photo}`, alt: "", loading: "lazy" });
    img.addEventListener("error", () => img.remove());
    el.append(img);
  }
  return el;
}

/** The emoji of a reaction: plain emoji, a custom emoji image, or a star for paid reactions. */
function reactionIcon(reaction) {
  if (reaction.custom_emoji_id) {
    const img = h("img", { class: "custom-emoji", src: `/api/telegram/custom-emoji/${reaction.custom_emoji_id}`, alt: "★" });
    img.addEventListener("error", () => img.replaceWith("★"));
    return img;
  }
  if (reaction.paid) return "⭐";
  // Telegram sends e.g. ❤ without the emoji variation selector; browsers then draw a plain text symbol
  return [...reaction.emoji].length === 1 ? reaction.emoji + "\uFE0F" : reaction.emoji;
}

// ==========================================
// TELEGRAM HTML SANITIZER
// ==========================================
// Message HTML comes from Telegram (via Telethon). It is parsed in an inert document and
// rebuilt from these tags only; all other tags keep their text, all attributes are dropped
// except safe link targets.
const ALLOWED_TAGS = {
  STRONG: "strong", B: "strong", EM: "em", I: "em", U: "u", DEL: "del", S: "del",
  CODE: "code", PRE: "pre", BLOCKQUOTE: "blockquote", A: "a", BR: "br",
  "TG-EMOJI": "span", SPAN: "span",
};
const SAFE_LINK = /^(https?:|tg:|mailto:)/i;

function sanitizeTelegramHtml(html) {
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");
  const fragment = document.createDocumentFragment();
  copySafeNodes(doc.body, fragment);
  return fragment;
}

function copySafeNodes(source, target) {
  for (const node of source.childNodes) {
    if (node.nodeType === Node.TEXT_NODE) {
      target.append(document.createTextNode(node.data));
      continue;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) continue;

    const tag = ALLOWED_TAGS[node.tagName];
    if (!tag) {
      copySafeNodes(node, target);
      continue;
    }
    const el = document.createElement(tag);
    if (tag === "a") {
      const href = (node.getAttribute("href") || "").trim();
      if (SAFE_LINK.test(href)) {
        el.href = href;
        el.target = "_blank";
        el.rel = "noopener noreferrer";
      }
    }
    copySafeNodes(node, el);
    target.append(el);
  }
}

// ==========================================
// APP STATE AND ROUTING
// ==========================================
const app = { status: null, view: null };
const viewRoot = () => document.getElementById("view");

async function refreshStatus() {
  try {
    app.status = await api("/api/status");
  } catch {
    app.status = null;
  }
  const dot = document.getElementById("status-dot");
  const state = app.status ? app.status.telegram.state : "offline";
  dot.className = "status-dot " + (state === "ready" ? "ready" : state === "connecting" ? "" : "problem");
  dot.title = {
    ready: "Telegram connected",
    connecting: "Connecting to Telegram...",
    offline: "VTP server not reachable",
  }[state] || "Telegram needs attention: open Setup";
  return app.status;
}

const telegramReady = () => app.status && app.status.telegram.state === "ready";

function currentRoute() {
  const [page, arg] = location.hash.replace(/^#\/?/, "").split("/");
  return { page: page || "telegram", arg };
}

async function route() {
  const { page, arg } = currentRoute();
  document.querySelectorAll(".tabs a").forEach((a) => a.classList.toggle("active", a.dataset.tab === page));

  if (page === "setup") {
    app.view = null;
    await renderSetup();
    return;
  }
  if (!(app.view instanceof TelegramView)) {
    app.view = new TelegramView();
    app.view.mount();
  }
  app.view.openChat(arg ? Number(arg) : null);
}

// ==========================================
// TELEGRAM VIEWER
// ==========================================
// Messages per request, as in telegram_service.list_messages()
const PAGE_SIZE = 30;

function groupAlbums(messages) {
  const groups = [];
  for (const msg of messages) {
    const last = groups[groups.length - 1];
    if (last && msg.grouped_id && last[0].grouped_id === msg.grouped_id) last.push(msg);
    else groups.push([msg]);
  }
  return groups;
}

function prettyAction(action) {
  const words = action.replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

class TelegramView {
  constructor() {
    this.dialogs = [];
    this.shortcuts = [];
    this.chat = null;
    this.reloadTimer = null;
    this.dialogTimer = null;
  }

  mount() {
    const view = viewRoot();
    if (!telegramReady()) {
      this.unavailable = true;
      const state = app.status ? app.status.telegram.state : "offline";
      view.replaceChildren(h("div", { class: "page" }, h("div", { class: "card" },
        h("h2", {}, "Telegram"),
        state === "connecting"
          ? h("p", { class: "muted" }, "Connecting to Telegram...")
          : h("p", {}, "Telegram isn't connected yet. ", h("a", { href: "#/setup" }, "Open Setup"), " to log in."))));
      return;
    }

    this.shortcutList = h("ul", { class: "chat-items" });
    this.dialogList = h("ul", { class: "chat-items" });
    this.moreButton = h("button", { class: "btn", onclick: () => this.loadDialogs(true) }, "Load more chats");
    const list = h("aside", { class: "tg-list" },
      h("div", { class: "tg-section-title" }, "Shortcuts"), this.shortcutList,
      h("div", { class: "tg-section-title" }, "Chats"), this.dialogList,
      h("div", { class: "list-footer" }, this.moreButton));

    this.chatTitle = h("div", { class: "title" });
    this.messagesBox = h("div", { class: "messages" });
    const chatPane = h("section", { class: "tg-chat" },
      h("header", { class: "chat-head" },
        h("button", { class: "icon-btn back", title: "Back to chats", onclick: () => { location.hash = "#/telegram"; } }, "←"),
        this.chatTitle,
        h("button", { class: "icon-btn", title: "Reload messages", onclick: () => this.reloadChat() }, "⟳")),
      this.messagesBox);

    this.root = h("div", { class: "tg" }, list, chatPane);
    view.replaceChildren(this.root);
    this.loadShortcuts();
    this.loadDialogs(false);
  }

  // ---------------------------------------------------------------- chat list
  async loadShortcuts() {
    try {
      this.shortcuts = await api("/api/telegram/shortcuts");
    } catch (e) {
      this.shortcutList.replaceChildren(h("li", { class: "chat-item error" }, e.message));
      return;
    }
    this.renderShortcuts();
  }

  renderShortcuts() {
    if (!this.shortcuts.length) {
      this.shortcutList.replaceChildren(h("li", { class: "chat-item muted" }, "No channels in _config/channels.json"));
      return;
    }
    this.shortcutList.replaceChildren(...this.shortcuts.map((s) => this.chatItem({
      id: s.chat_id, name: s.name, photo: s.photo, label: s.label, preview: s.error ? `Not found: ${s.error}` : "",
    })));
  }

  async loadDialogs(more) {
    this.moreButton.disabled = true;
    try {
      const last = more ? this.dialogs[this.dialogs.length - 1] : null;
      const query = last && last.date ? `?offset_date=${encodeURIComponent(last.date)}` : "";
      const page = await api(`/api/telegram/dialogs${query}`);
      if (more) {
        for (const d of page) if (!this.dialogs.some((x) => x.id === d.id)) this.dialogs.push(d);
      } else {
        // First page replaces the top of the list; chats loaded with "Load more" stay below it
        const ids = new Set(page.map((d) => d.id));
        this.dialogs = page.concat(this.dialogs.filter((d) => !ids.has(d.id)));
      }
      this.moreButton.hidden = more && page.length === 0;
      this.renderDialogs();
    } catch (e) {
      this.dialogList.replaceChildren(h("li", { class: "chat-item error" }, e.message));
    } finally {
      this.moreButton.disabled = false;
    }
  }

  renderDialogs() {
    this.dialogList.replaceChildren(...this.dialogs.map((d) => this.chatItem(d)));
  }

  chatItem({ id, name, photo, label, preview, date, unread, unread_reactions }) {
    const active = this.chat && this.chat.id === id;
    return h("li", {
      class: "chat-item" + (active ? " active" : ""),
      "data-chat": id,
      onclick: () => { if (id) location.hash = `#/telegram/${id}`; },
    },
      avatar(name, id, photo),
      h("div", { class: "chat-text" },
        h("div", { class: "chat-line" },
          h("span", { class: "chat-name", dir: "auto" }, name),
          date ? h("span", { class: "chat-time" }, listTime(date)) : null),
        h("div", { class: "chat-line" },
          label ? h("span", { class: "chat-label" }, label) : null,
          h("span", { class: "chat-preview", dir: "auto" }, preview || ""),
          unread_reactions ? h("span", {
            class: "reaction-badge",
            title: `${unread_reactions} new reaction${unread_reactions > 1 ? "s" : ""} to your messages`,
          }, unread_reactions > 1 ? `♥ ${unread_reactions}` : "♥") : null,
          unread ? h("span", { class: "unread" }, unread) : null)));
  }

  highlightActive() {
    for (const item of this.root.querySelectorAll(".chat-item[data-chat]")) {
      item.classList.toggle("active", !!this.chat && Number(item.dataset.chat) === this.chat.id);
    }
  }

  knownName(id) {
    const match = this.dialogs.find((d) => d.id === id) || this.shortcuts.find((s) => s.chat_id === id);
    return match ? match.name : null;
  }

  setChatTitle(name, details, photo) {
    const id = this.chat ? this.chat.id : null;
    this.chatTitle.replaceChildren(
      id ? avatar(name, id, photo, "small") : "",
      h("div", { class: "title-text" }, h("strong", { dir: "auto" }, name), details ? h("small", {}, details) : null));
  }

  // ---------------------------------------------------------------- open chat
  async openChat(id) {
    if (this.unavailable) return;
    this.root.classList.toggle("show-chat", !!id);
    if (!id) {
      this.chat = null;
      this.highlightActive();
      this.setChatTitle("Telegram");
      this.messagesBox.replaceChildren(h("div", { class: "empty-state" }, "Choose a chat to read it here."));
      return;
    }
    if (this.chat && this.chat.id === id) return;

    // reactorLists: message ID -> everyone who reacted, once "Who reacted" was clicked
    const chat = { id, info: null, messages: new Map(), reactorLists: new Map(), noOlder: false };
    this.chat = chat;
    this.highlightActive();
    this.setChatTitle(this.knownName(id) || "Loading...");
    this.messagesBox.replaceChildren(h("div", { class: "empty-state" }, "Loading messages..."));

    try {
      const [info, messages] = await Promise.all([
        api(`/api/telegram/chats/${id}`),
        api(`/api/telegram/chats/${id}/messages`),
      ]);
      if (this.chat !== chat) return; // another chat was opened meanwhile
      chat.info = info;
      chat.noOlder = messages.length < PAGE_SIZE;
      this.renderChatTitle();
      this.addMessages(messages);
      this.renderMessages({ scroll: "bottom" });
    } catch (e) {
      if (this.chat === chat) this.messagesBox.replaceChildren(h("div", { class: "empty-state error" }, e.message));
    }
  }

  renderChatTitle() {
    const { info } = this.chat;
    const details = [info.kind, info.username ? "@" + info.username : null].filter(Boolean).join(" · ");
    this.setChatTitle(info.name, details, info.photo);
  }

  addMessages(messages) {
    for (const msg of messages) this.chat.messages.set(msg.id, msg);
  }

  async loadOlder(button) {
    const chat = this.chat;
    button.disabled = true;
    const oldest = Math.min(...chat.messages.keys());
    const fromBottom = this.messagesBox.scrollHeight - this.messagesBox.scrollTop;
    try {
      const messages = await api(`/api/telegram/chats/${chat.id}/messages?offset_id=${oldest}`);
      if (this.chat !== chat) return;
      if (messages.length < PAGE_SIZE) chat.noOlder = true;
      this.addMessages(messages);
      this.renderMessages({ fromBottom });
    } catch (e) {
      button.disabled = false;
      button.textContent = `Couldn't load: ${e.message}. Try again`;
    }
  }

  /** Reloads the newest page of the open chat (new messages, or the reload button). */
  async reloadChat() {
    const chat = this.chat;
    if (!chat || !chat.info) return;
    const box = this.messagesBox;
    const wasAtBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
    try {
      const messages = await api(`/api/telegram/chats/${chat.id}/messages`);
      if (this.chat !== chat) return;
      this.addMessages(messages);
      this.renderMessages(wasAtBottom ? { scroll: "bottom" } : { scrollTop: box.scrollTop });
    } catch {
      /* the next update or the reload button tries again */
    }
  }

  /** Re-fetches messages that are on screen, e.g. after an edit or a reaction, wherever they are. */
  async refreshMessages(ids) {
    const chat = this.chat;
    if (!chat || !chat.info) return;
    let changed = false;
    for (const id of ids) {
      if (!chat.messages.has(id)) continue;
      try {
        chat.messages.set(id, await api(`/api/telegram/chats/${chat.id}/messages/${id}`));
        if (chat.reactorLists.has(id)) {
          chat.reactorLists.set(id, await api(`/api/telegram/chats/${chat.id}/messages/${id}/reactions`));
        }
        changed = true;
      } catch {
        /* deleted meanwhile, or a temporary error: the reload button fetches it again */
      }
    }
    if (changed && this.chat === chat) this.renderMessages({ scrollTop: this.messagesBox.scrollTop });
  }

  async loadReactors(msgId, button) {
    const chat = this.chat;
    button.disabled = true;
    try {
      const reactors = await api(`/api/telegram/chats/${chat.id}/messages/${msgId}/reactions`);
      if (this.chat !== chat) return;
      chat.reactorLists.set(msgId, reactors);
      this.renderMessages({ scrollTop: this.messagesBox.scrollTop });
    } catch (e) {
      button.disabled = false;
      button.textContent = `Couldn't load: ${e.message}`;
    }
  }

  renderMessages(position) {
    const chat = this.chat;
    const box = this.messagesBox;
    const sorted = [...chat.messages.values()].sort((a, b) => a.id - b.id);
    const nodes = [];

    if (!sorted.length) {
      nodes.push(h("div", { class: "empty-state" }, "No messages."));
    } else if (!chat.noOlder) {
      nodes.push(h("button", { class: "btn load-older", onclick: (e) => this.loadOlder(e.currentTarget) }, "Load older messages"));
    }

    let lastDay = null;
    for (const group of groupAlbums(sorted)) {
      const date = new Date(group[0].date);
      if (date.toDateString() !== lastDay) {
        lastDay = date.toDateString();
        nodes.push(h("div", { class: "day" }, dayFormat.format(date)));
      }
      nodes.push(group[0].service ? h("div", { class: "service" }, prettyAction(group[0].service)) : this.bubble(group));
    }
    box.replaceChildren(...nodes);

    if (position.scroll === "bottom") {
      box.scrollTop = box.scrollHeight;
    } else if (position.fromBottom !== undefined) {
      box.scrollTop = box.scrollHeight - position.fromBottom;
    } else if (position.scrollTop !== undefined) {
      box.scrollTop = position.scrollTop;
    }
  }

  bubble(group) {
    const kind = this.chat.info.kind;
    const first = group[0];
    const withText = group.find((m) => m.html) || first;
    const images = group.filter((m) => m.has_image);
    const parts = [];

    if (withText.sender && (kind === "group" ? !first.out : kind === "channel")) {
      parts.push(h("div", { class: "sender", dir: "auto" }, withText.sender));
    }

    if (images.length) {
      const layout = images.length === 1 ? "single" : images.length <= 4 ? `n${images.length}` : "many";
      parts.push(h("div", { class: `media-grid ${layout}` }, images.map((m) => {
        const src = `/api/telegram/media/${this.chat.id}/${m.id}`;
        // width/height reserve the image's space before it loads, so redrawing doesn't move the scroll position
        const [width, height] = m.image_size || [];
        return h("a", { href: src, target: "_blank", rel: "noopener" },
          h("img", { src, width, height, loading: "lazy", alt: m.media || "Image" }));
      })));
    }

    for (const m of group) {
      if (m.media && m.media !== "Photo") {
        parts.push(h("div", { class: "media-note", dir: "auto" }, `📎 ${m.media}${m.file_name ? ": " + m.file_name : ""}`));
      }
    }

    if (withText.html) {
      const text = h("div", { class: "text", dir: "auto" });
      text.append(sanitizeTelegramHtml(withText.html));
      parts.push(text);
    }

    const withReactions = group.find((m) => m.reactions);
    if (withReactions) parts.push(this.reactionsBlock(withReactions));

    const meta = [];
    if (withText.views !== null && withText.views !== undefined) meta.push(`👁 ${compactNumber.format(withText.views)}`);
    if (withText.edit_date) meta.push("edited");
    meta.push(timeFormat.format(new Date(first.date)));
    parts.push(h("div", { class: "meta" }, meta.join(" · ")));

    const isOut = first.out && kind !== "channel";
    return h("div", { class: "msg" + (isOut ? " out" : ""), "data-id": first.id }, h("div", { class: "bubble" }, parts));
  }

  /** Reaction counts, then who reacted (recent reactors, or everyone after "Who reacted"). */
  reactionsBlock(msg) {
    const { results, recent, can_see_list } = msg.reactions;
    const block = h("div", { class: "reactions-block" },
      h("div", { class: "reactions" }, results.map((r) =>
        h("span", { class: "reaction" + (r.mine ? " mine" : ""), title: r.mine ? "Your reaction" : null },
          reactionIcon(r), ` ${r.count}`))));

    const everyone = this.chat.reactorLists.get(msg.id);
    const people = everyone || recent;
    if (people.length) {
      block.append(h("div", { class: "reactors" }, people.map((p) =>
        h("span", { class: "reactor" + (p.unread ? " unseen" : ""), title: p.unread ? "New reaction" : null },
          reactionIcon(p), " ", h("bdi", {}, p.mine ? "You" : p.name)))));
    }

    const total = results.reduce((sum, r) => sum + r.count, 0);
    if (can_see_list && !everyone && total > recent.length) {
      block.append(h("button", { class: "link-btn reactors-more", onclick: (e) => this.loadReactors(msg.id, e.currentTarget) },
        "Who reacted"));
    }
    return block;
  }

  // ---------------------------------------------------------------- live updates
  onUpdate(update) {
    if (this.unavailable) return;
    // Deletions in private chats and small groups arrive without a chat ID
    const isOpen = this.chat && (this.chat.id === update.chat_id || (update.chat_id === null && update.type === "deleted"));
    if (isOpen && update.type === "new") {
      clearTimeout(this.reloadTimer);
      this.reloadTimer = setTimeout(() => this.reloadChat(), 400);
    } else if (isOpen && update.type === "deleted") {
      for (const id of update.ids) this.chat.messages.delete(id);
      this.renderMessages({ scrollTop: this.messagesBox.scrollTop });
    } else if (isOpen) {
      this.refreshMessages(update.ids); // edited, or reactions changed
    }
    clearTimeout(this.dialogTimer);
    this.dialogTimer = setTimeout(() => this.loadDialogs(false), 1500);
  }
}

// ==========================================
// SETUP PAGE
// ==========================================
function field(label, attrs) {
  return h("label", {}, label, h("input", attrs));
}

/** A form whose submit calls `submit(values)`; errors are shown under the fields. */
function actionForm(fields, buttonText, submit) {
  const message = h("p", { class: "error", hidden: true });
  const button = h("button", { class: "btn primary", type: "submit" }, buttonText);
  const form = h("form", { class: "form" }, fields, message, h("div", { class: "btn-row" }, button));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    button.disabled = true;
    message.hidden = true;
    try {
      await submit(Object.fromEntries(new FormData(form)));
    } catch (e) {
      message.textContent = e.message;
      message.hidden = false;
    } finally {
      button.disabled = false;
    }
  });
  return form;
}

const setupNotes = { gemini: null, changePhone: false };

async function renderSetup() {
  const status = await refreshStatus();
  if (currentRoute().page !== "setup") return;
  if (!status) {
    viewRoot().replaceChildren(h("div", { class: "page" }, h("div", { class: "card" },
      h("p", { class: "error" }, "The VTP server isn't responding. Is it still running?"))));
    return;
  }
  viewRoot().replaceChildren(h("div", { class: "page" },
    telegramCard(status.telegram), geminiCard(status.gemini), systemCard(status)));

  // Keep polling while the Telegram connection is still being set up
  if (status.telegram.state === "connecting") setTimeout(() => { if (currentRoute().page === "setup") renderSetup(); }, 2000);
}

function telegramCard(t) {
  const card = h("div", { class: "card" }, h("h2", {}, "Telegram"));
  const done = () => { setupNotes.changePhone = false; return renderSetup(); };

  if (t.state === "connecting") {
    card.append(h("p", { class: "muted" }, "Connecting to Telegram..."));
  } else if (t.state === "ready") {
    card.append(
      h("p", { class: "ok" }, `Logged in as ${t.me.name}${t.me.username ? " (@" + t.me.username + ")" : ""}.`),
      h("p", { class: "muted" }, "To use another account, stop the server and delete _credentials/user_session.session."));
  } else if (t.state === "no_credentials") {
    card.append(
      h("p", {}, "VTP needs an API ID and API hash for your Telegram account. Create an app under ",
        h("a", { href: "https://my.telegram.org/apps", target: "_blank", rel: "noopener" }, "my.telegram.org"),
        " (API development tools) and paste its values here."),
      h("p", { class: "muted" }, "They're saved in _credentials/telegram_api.json."),
      actionForm([
        field("API ID", { name: "api_id", type: "number", required: true, inputmode: "numeric" }),
        field("API hash", { name: "api_hash", type: "text", required: true, autocomplete: "off", spellcheck: "false" }),
      ], "Save", async (v) => { await api("/api/setup/telegram-api", { json: { api_id: Number(v.api_id), api_hash: v.api_hash } }); await done(); }));
  } else if (t.state === "error") {
    card.append(
      h("p", { class: "error" }, t.error || "Telegram connection failed."),
      actionForm([], "Try again", async () => { await api("/api/telegram/reconnect", { json: {} }); await done(); }));
  } else if (t.login_step === "code" && !setupNotes.changePhone) {
    card.append(
      h("p", {}, `Telegram sent a login code to ${t.login_phone}. It arrives in the Telegram app on your other devices, or by SMS.`),
      actionForm([field("Login code", { name: "code", type: "text", required: true, inputmode: "numeric", autocomplete: "one-time-code" })],
        "Log in", async (v) => { await api("/api/login/code", { json: { code: v.code } }); await done(); }),
      h("p", {}, h("button", { class: "link-btn", onclick: () => { setupNotes.changePhone = true; renderSetup(); } }, "Use a different number")));
  } else if (t.login_step === "password") {
    card.append(
      h("p", {}, "This account has two-step verification. Enter its password."),
      actionForm([field("Password", { name: "password", type: "password", required: true, autocomplete: "current-password" })],
        "Log in", async (v) => { await api("/api/login/password", { json: { password: v.password } }); await done(); }));
  } else {
    card.append(
      h("p", {}, "Log in with the phone number of the Telegram account VTP should use."),
      actionForm([field("Phone number with country code", { name: "phone", type: "tel", required: true, placeholder: "+98...", autocomplete: "tel" })],
        "Send code", async (v) => { await api("/api/login/phone", { json: { phone: v.phone } }); await done(); }));
  }
  return card;
}

function geminiCard(g) {
  const card = h("div", { class: "card" }, h("h2", {}, "Gemini"));
  card.append(g.key_set
    ? h("p", { class: "ok" }, `An API key is saved. Last used model: ${g.model || "none yet"}.`)
    : h("p", { class: "warn" }, "No API key saved. The translation step needs one."));
  if (setupNotes.gemini) {
    card.append(h("p", { class: setupNotes.gemini.warning ? "warn" : "ok" },
      setupNotes.gemini.warning || `Key saved. ${setupNotes.gemini.models} models available.`));
    setupNotes.gemini = null;
  }
  card.append(
    h("p", { class: "muted" }, "Get a key from ",
      h("a", { href: "https://aistudio.google.com/apikey", target: "_blank", rel: "noopener" }, "Google AI Studio"),
      ". It's saved in _credentials/gemini_keys.json."),
    actionForm([field(g.key_set ? "Replace API key" : "API key", { name: "api_key", type: "password", required: true, autocomplete: "off" })],
      "Save key", async (v) => { setupNotes.gemini = await api("/api/setup/gemini", { json: { api_key: v.api_key } }); await renderSetup(); }));
  return card;
}

function systemCard(status) {
  const config = status.config;
  let configText;
  if (!config.exists) {
    configText = h("p", { class: "warn" }, "No _config/channels.json yet. Create it with python kernel/configurator.py, or copy it from an existing install.");
  } else if (config.error) {
    configText = h("p", { class: "error" }, `_config/channels.json can't be read: ${config.error}`);
  } else {
    configText = h("p", { class: "ok" }, `${config.channels} channels configured in _config/channels.json.`);
  }
  return h("div", { class: "card" }, h("h2", {}, "Rendering and channels"),
    configText,
    status.raqm
      ? h("p", { class: "ok" }, "Raqm text layout is active: Kurdish, Persian and Arabic headlines render correctly.")
      : h("p", { class: "warn" }, "Raqm text layout is not active: Kurdish ڵ ڕ ێ will render without their V mark. Run setup again to install FriBiDi."));
}

// ==========================================
// START
// ==========================================
function startLiveUpdates() {
  const source = new EventSource("/api/events");
  source.onmessage = (event) => {
    if (app.view instanceof TelegramView) app.view.onUpdate(JSON.parse(event.data));
  };
}

async function watchStatus() {
  const before = app.status ? app.status.telegram.state : null;
  await refreshStatus();
  const after = app.status ? app.status.telegram.state : null;
  // When Telegram becomes ready (or drops), rebuild the viewer
  if (before !== after && currentRoute().page === "telegram") {
    app.view = null;
    route();
  }
}

(async function start() {
  await refreshStatus();
  window.addEventListener("hashchange", route);
  await route();
  startLiveUpdates();
  setInterval(watchStatus, 5000);
})();
