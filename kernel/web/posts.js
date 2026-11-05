"use strict";
// The pipeline pages: the post list, a new post, and one post's texts, images, captions and publishing.
// Uses the helpers from app.js (api, h, sanitizeTelegramHtml, ...).

const sessionUrl = (name, path = "") => `/api/sessions/${encodeURIComponent(name)}${path}`;
const sessionFileUrl = (name, file, version) => sessionUrl(name, `/files/${encodeURIComponent(file)}`) + (version ? `?v=${version}` : "");
const dateTimeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

/** Saves after typing pauses (or at once with flush), and shows "Saving..." / "Saved" in statusEl. */
function autosave(save, statusEl, delay = 800) {
  let timer = null;
  const run = async () => {
    timer = null;
    statusEl.textContent = "Saving...";
    statusEl.className = "save-status muted";
    try {
      await save();
      statusEl.textContent = "Saved";
      statusEl.className = "save-status ok";
    } catch (e) {
      statusEl.textContent = `Not saved: ${e.message}`;
      statusEl.className = "save-status error";
    }
  };
  return {
    schedule() {
      clearTimeout(timer);
      statusEl.textContent = "Editing...";
      statusEl.className = "save-status muted";
      timer = setTimeout(run, delay);
    },
    flush() {
      if (timer) {
        clearTimeout(timer);
        run();
      }
    },
  };
}

/** Runs an action from a button: disables it, shows `busyText`, and reports errors in errorEl. */
async function withButton(button, busyText, action, errorEl) {
  const label = button.textContent;
  button.disabled = true;
  button.textContent = busyText;
  if (errorEl) errorEl.hidden = true;
  try {
    return await action();
  } catch (e) {
    if (errorEl) {
      errorEl.textContent = e.message;
      errorEl.hidden = false;
    }
    return null;
  } finally {
    if (button.isConnected) {
      button.disabled = false;
      button.textContent = label;
    }
  }
}

// ==========================================
// POST LIST
// ==========================================
async function renderPosts() {
  const page = h("div", { class: "page wide" },
    h("div", { class: "page-head" },
      h("h1", {}, "Posts"),
      h("a", { class: "btn primary", href: "#/post/new", onclick: () => { app.draft = null; } }, "New post")),
    h("p", { class: "muted" },
      "To start from Telegram messages, open the chat in the Telegram tab, tap Select, pick the messages, then Start post."));
  const list = h("div", { class: "post-list" }, h("p", { class: "muted" }, "Loading..."));
  page.append(list);
  viewRoot().replaceChildren(page);

  let sessions;
  try {
    sessions = await api("/api/sessions");
  } catch (e) {
    list.replaceChildren(h("p", { class: "error" }, e.message));
    return;
  }
  if (!sessions.length) {
    list.replaceChildren(h("p", { class: "muted" }, "No posts yet."));
    return;
  }
  list.replaceChildren(...sessions.map((s) => {
    const status = [];
    if (s.video) status.push(s.videos ? `video · ${s.videos} rendered` : "video");
    else if (s.images) status.push(`${s.images} images`);
    if (s.previews) status.push("previews sent");
    if (s.published) status.push(`published to ${s.published}`);
    return h("a", { class: "post-item", href: `#/post/${encodeURIComponent(s.name)}` },
      h("span", { class: "post-thumb" },
        s.thumbnail
          ? h("img", { src: sessionFileUrl(s.name, s.thumbnail, s.thumbnail_version), alt: "", loading: "lazy" })
          : h("span", { class: "post-thumb-empty" }),
        s.video ? h("span", { class: "play-mark" }, "▶") : null),
      h("span", { class: "post-item-text" },
        h("strong", { dir: "auto" }, s.title),
        h("small", { class: "muted" }, [s.created ? dateTimeFormat.format(new Date(s.created)) : "", ...status].filter(Boolean).join(" · "))));
  }));
}

// ==========================================
// NEW POST
// ==========================================
// Browsers leave the type empty for some video files (e.g. .mkv)
const VIDEO_NAME = /\.(mp4|m4v|mov|mkv|webm|avi|3gp|ts|mts|m2ts|flv|wmv|mpg|mpeg)$/i;
const isVideoFile = (file) => file.type.startsWith("video/") || (!file.type && VIDEO_NAME.test(file.name));

/** A silent video that plays in a loop, like the area editor's. */
function loopingVideo(src, poster, className) {
  const video = h("video", { class: className, src, poster, loop: true, playsinline: true, disablepictureinpicture: true });
  video.muted = true; // must be set as a property for the browser to allow autoplay
  video.play().catch(() => { /* shows the poster */ });
  return video;
}

/** The uploaded video playing silently in its tile, or its name if the browser can't play it. */
function uploadedVideo(url, fileName) {
  const video = h("video", { src: url, loop: true, playsinline: true });
  video.muted = true;
  video.addEventListener("error", () => video.replaceWith(h("span", { class: "video-tile", dir: "auto" }, fileName)));
  video.play().catch(() => { /* shown paused */ });
  return video;
}
class NewPostView {
  async mount() {
    // The draft survives switching tabs, so a failed translation can be retried with another model
    const draft = app.draft || (app.draft = { text: "", photos: [], chosen: null, source: "" });
    this.draft = draft;

    const text = h("textarea", { rows: 12, dir: "auto", placeholder: "Paste the news text. Start each language with its headline." }, draft.text);
    text.addEventListener("input", () => { draft.text = text.value; });

    this.photoGrid = h("div", { class: "photo-choices" });
    this.modelSelect = h("select", { class: "model-select" }, h("option", {}, "Loading models..."));
    this.modelNote = h("p", { class: "muted small" });
    this.error = h("p", { class: "error", hidden: true });
    this.status = h("p", { class: "muted", hidden: true });
    const submit = h("button", { class: "btn primary", onclick: (e) => this.submit(e.currentTarget) }, "Translate and create post");

    viewRoot().replaceChildren(h("div", { class: "page" },
      h("div", { class: "page-head" }, h("a", { href: "#/posts" }, "← Posts"), h("h1", {}, "New post")),
      h("div", { class: "card" },
        h("h2", {}, "Text"),
        draft.source ? h("p", { class: "muted" }, `From ${draft.source}. Edit it before translating if needed.`) : null,
        h("p", { class: "muted small" }, "Languages that are already in the text are kept as they are; missing ones are translated."),
        text),
      h("div", { class: "card" }, h("h2", {}, "Photo or video"), this.photoGrid),
      h("div", { class: "card" },
        h("h2", {}, "Translate"),
        h("label", { class: "field" }, "Gemini model", this.modelSelect),
        this.modelNote,
        this.error, this.status,
        h("div", { class: "btn-row" }, submit))));

    this.renderPhotos();
    this.loadModels();
  }

  renderPhotos() {
    const draft = this.draft;
    const chosen = draft.chosen;
    const tiles = draft.photos.map((p) => {
      const isChosen = chosen && chosen.type === "telegram" && chosen.msg_id === p.msg_id && chosen.chat_id === p.chat_id;
      // A video without a thumbnail has no picture to show
      const picture = p.video && !p.has_image
        ? h("span", { class: "video-tile" }, "Video")
        : h("img", { src: `/api/telegram/media/${p.chat_id}/${p.msg_id}`, alt: p.video ? "Video from Telegram" : "Photo from Telegram" });
      return h("button", {
        class: "photo-choice" + (isChosen ? " chosen" : ""), title: p.video ? "Use this video" : "Use this photo",
        onclick: () => { draft.chosen = { type: "telegram", ...p }; this.renderPhotos(); },
      }, picture, p.video ? h("span", { class: "play-mark" }, "▶") : null);
    });

    const fileInput = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp,image/avif,video/*", hidden: true });
    fileInput.addEventListener("change", () => {
      const file = fileInput.files[0];
      if (!file) return;
      if (draft.uploadPreview) URL.revokeObjectURL(draft.uploadPreview);
      draft.upload = file;
      draft.uploadPreview = URL.createObjectURL(file);
      draft.chosen = { type: "upload" };
      this.renderPhotos();
    });
    if (draft.upload) {
      const isVideo = isVideoFile(draft.upload);
      tiles.push(h("button", {
        class: "photo-choice" + (chosen && chosen.type === "upload" ? " chosen" : ""), title: isVideo ? "Use this video" : "Use this photo",
        onclick: () => { draft.chosen = { type: "upload" }; this.renderPhotos(); },
      }, isVideo ? uploadedVideo(draft.uploadPreview, draft.upload.name) : h("img", { src: draft.uploadPreview, alt: "Uploaded photo" }),
      isVideo ? h("span", { class: "play-mark" }, "▶") : null));
    }
    tiles.push(h("label", { class: "photo-choice upload" }, fileInput,
      h("span", {}, draft.upload ? "Choose another file" : "Upload a photo or video")));

    const hint = h("p", { class: "muted small" }, draft.photos.length
      ? "Tap the photo or video to use."
      : "Nothing picked from Telegram. Upload a photo or video, or select a photo or video message in the Telegram tab.");
    this.photoGrid.replaceChildren(hint, h("div", { class: "photo-tiles" }, tiles));
  }

  async loadModels() {
    const result = await api("/api/gemini/models").catch((e) => ({ models: [], last: null, error: e.message }));
    const models = result.models.slice();
    if (result.last && !models.includes(result.last)) models.unshift(result.last);
    this.modelSelect.replaceChildren(...models.map((m) => h("option", { value: m, selected: m === result.last }, m)));
    if (!models.length) this.modelSelect.append(h("option", { value: "" }, "No models available"));
    this.modelNote.textContent = result.error || "If a model is overloaded or returns bad data, choose another one and try again.";
    this.modelNote.className = result.error ? "warn small" : "muted small";
  }

  async submit(button) {
    const draft = this.draft;
    const show = (message) => {
      this.status.textContent = message;
      this.status.hidden = false;
    };
    await withButton(button, "Working...", async () => {
      if (!draft.text.trim()) throw new Error("Add the news text first.");
      if (!draft.chosen) throw new Error("Choose a photo or video first.");

      // Kept for retries with another model, so a video isn't uploaded and prepared again
      const choice = draft.chosen.type === "telegram" ? `${draft.chosen.chat_id}/${draft.chosen.msg_id}` : draft.upload;
      let token = draft.token && draft.token.choice === choice ? draft.token.value : null;
      if (!token) {
        const isVideo = draft.chosen.type === "telegram" ? draft.chosen.video : isVideoFile(draft.upload);
        show(isVideo ? "Preparing the video. A long video takes a while..." : "Preparing the photo...");
        if (draft.chosen.type === "telegram") {
          token = (await api("/api/uploads/telegram", { json: { chat_id: draft.chosen.chat_id, msg_id: draft.chosen.msg_id } })).token;
        } else {
          token = (await api("/api/uploads", {
            method: "POST", headers: { "Content-Type": draft.upload.type || "application/octet-stream" }, body: draft.upload,
          })).token;
        }
        draft.token = { choice, value: token };
      }

      const model = this.modelSelect.value || null;
      show(`Translating with ${model || "the last used model"}. This can take up to a minute...`);
      const { name } = await api("/api/sessions", { json: { text: draft.text, image_token: token, model } })
        .catch((e) => {
          if (e.status === 404) draft.token = null; // the upload was cleaned up; the next try sends it again
          throw e;
        });
      if (draft.uploadPreview) URL.revokeObjectURL(draft.uploadPreview);
      app.draft = null;
      location.hash = `#/post/${encodeURIComponent(name)}`;
    }, this.error);
    if (!this.error.hidden) this.status.hidden = true;
  }
}

// ==========================================
// ONE POST
// ==========================================
// Margin around the photo in the area editor, as a fraction of the photo's size. Like the terminal
// version's grid, the area may extend into it to add space around the subject.
const AOI_MARGIN = 0.25;

// Which post sections were last left open, kept in this browser for every post
const SECTIONS_KEY = "vtp.postSections";

function loadSectionState() {
  try {
    return JSON.parse(localStorage.getItem(SECTIONS_KEY)) || {};
  } catch {
    return {}; // storage blocked (e.g. a private window): use the defaults
  }
}

/** A post section that folds away under its heading. Only the body is redrawn, so it stays open or closed. */
function postSection(key, title, defaultOpen) {
  const saved = loadSectionState()[key];
  const body = h("div");
  const card = h("details", { class: "card post-section", open: typeof saved === "boolean" ? saved : defaultOpen },
    h("summary", {}, h("h2", {}, title)), body);
  // "toggle" also fires when a section is created open; only a change from the default is a choice to keep
  card.addEventListener("toggle", () => {
    const state = loadSectionState();
    if (!(key in state) && card.open === defaultOpen) return;
    try {
      localStorage.setItem(SECTIONS_KEY, JSON.stringify({ ...state, [key]: card.open }));
    } catch {
      /* not remembered, nothing else breaks */
    }
  });
  return { card, body };
}

class PostView {
  constructor(name) {
    this.name = name;
    this.detail = null;
    this.savers = [];
    this.jobs = new Map(); // "previews" | "published" -> running job
    this.reviewChat = null; // {id, name, photo} of the review channel, once resolved
    this.reviewPane = null; // the review chat shown under the publish buttons while previews exist
    this.publishedCards = new Map(); // "<chat>/<msg>" -> {card, pane} of each published post
    this.viewsTimer = null;
    this.renderOptions = null; // area and blur being edited, sent with "Render images"
    this.chosenChannels = new Set(); // none ticked at first: picking a few is quicker than unticking most
    this.channelCards = new Map(); // channel -> its card in section 2, replaced alone when its video is done
    this.renderStatus = new Map(); // channel -> where a video post's card shows how its render is going
  }

  async mount() {
    viewRoot().replaceChildren(h("div", { class: "page wide" }, h("p", { class: "muted" }, "Loading post...")));
    try {
      this.detail = await api(sessionUrl(this.name));
    } catch (e) {
      viewRoot().replaceChildren(h("div", { class: "page" }, h("a", { href: "#/posts" }, "← Posts"),
        h("div", { class: "card" }, h("p", { class: "error" }, e.message))));
      return;
    }
    for (const job of this.detail.jobs) this.jobs.set(job.kind, job);
    this.renderOptions = { aoi: this.detail.render.aoi, blur: this.detail.render.blur, mute: this.detail.render.mute };

    // Until the user opens or closes one, captions start folded: they rarely need changes
    const texts = postSection("texts", "1. Texts", true);
    const images = postSection("images", this.detail.video ? "2. Video" : "2. Images", true);
    const captions = postSection("captions", "3. Captions", false);
    const publish = postSection("publish", "4. Publish", true);
    this.textsCard = texts.body;
    this.imagesCard = images.body;
    this.captionsCard = captions.body;
    // The controls are redrawn on every progress update. The published posts and the review chat
    // below them keep their elements across redraws, so loaded messages and scroll positions survive.
    this.publishControls = h("div");
    this.publishedSection = h("div", { class: "published-section" });
    this.reviewSection = h("div", { class: "review-embed" });
    publish.body.append(this.publishControls, this.publishedSection, this.reviewSection);
    const created = this.detail.created ? dateTimeFormat.format(new Date(this.detail.created)) : "";
    viewRoot().replaceChildren(h("div", { class: "page wide" },
      h("div", { class: "page-head" },
        h("a", { href: "#/posts" }, "← Posts"),
        h("h1", { dir: "auto" }, this.detail.title),
        h("small", { class: "muted" }, created)),
      texts.card, images.card, captions.card, publish.card));

    this.renderTexts();
    this.renderImages();
    this.renderCaptions();
    this.renderPublish();
    this.renderPublished();
    this.renderReviewSection();
    this.loadReviewChat();
  }

  leave() {
    for (const saver of this.savers) saver.flush();
    clearInterval(this.viewsTimer);
  }

  /** Applies post details returned by an action and redraws everything except the text editors. */
  update(detail) {
    if (!detail) return;
    this.detail = detail;
    for (const job of detail.jobs || []) this.jobs.set(job.kind, job);
    this.renderImages();
    this.renderCaptions();
    this.renderPublish();
    this.renderPublished();
    this.renderReviewSection();
  }

  async reload() {
    this.update(await api(sessionUrl(this.name)));
  }

  // ---------------------------------------------------------------- 1. texts
  renderTexts() {
    const card = this.textsCard;
    card.replaceChildren(
      h("p", { class: "muted small" }, "Changes are saved automatically. The headline is drawn on the images; captions are made from the headline and the body."));
    for (const lang of this.detail.languages) {
      const headline = h("input", { type: "text", dir: "auto", value: lang.headline });
      const body = h("textarea", { rows: 7, dir: "auto" }, lang.body);
      const status = h("span", { class: "save-status" });
      const summary = h("span", { class: "summary-text", dir: "auto" }, lang.exists ? lang.headline : "Missing: no translation yet");
      const saver = autosave(async () => {
        await api(sessionUrl(this.name, `/texts/${lang.code}`), { method: "PUT", json: { headline: headline.value, body: body.value } });
        await this.reload(); // images and captions made from the old text get marked as outdated
      }, status);
      this.savers.push(saver);
      for (const field of [headline, body]) {
        field.addEventListener("input", () => {
          summary.textContent = headline.value;
          saver.schedule();
        });
        field.addEventListener("blur", () => saver.flush());
      }
      card.append(h("details", { class: "lang-block", open: lang.code === "en" },
        h("summary", {}, h("strong", {}, lang.code.toUpperCase()), summary, status),
        h("label", { class: "field" }, "Headline", headline),
        h("label", { class: "field" }, "Body", body)));
    }
  }

  // ---------------------------------------------------------------- 2. images
  renderImages() {
    const card = this.imagesCard;
    const d = this.detail;
    card.replaceChildren();
    this.channelCards.clear();
    this.renderStatus.clear();
    if (!d.raw_image) {
      card.append(h("p", { class: "error" }, "This post has no photo (raw_image.*)."));
      return;
    }

    const error = h("p", { class: "error", hidden: true });
    const blurValue = h("span", {}, String(this.renderOptions.blur));
    const blur = h("input", { type: "range", min: 0, max: 60, step: 1, value: this.renderOptions.blur });
    blur.addEventListener("input", () => {
      this.renderOptions.blur = Number(blur.value);
      blurValue.textContent = blur.value;
    });
    const rendered = d.channels.some((c) => c.image);
    const what = d.video ? "" : " images";
    const renderButton = h("button", { class: "btn primary" }, rendered ? `Render${what} again` : `Render${what}`);
    renderButton.addEventListener("click", () => withButton(renderButton, "Rendering...", async () => {
      this.update(await api(sessionUrl(this.name, "/render"), { json: this.renderOptions }));
    }, error));

    card.append(
      h("div", { class: "render-options" },
        this.aoiEditor(),
        h("div", { class: "render-controls" },
          h("label", { class: "field" }, h("span", {}, "Background blur: ", blurValue), blur),
          d.video ? this.muteOption() : null,
          h("div", { class: "btn-row" }, renderButton),
          d.video ? h("p", { class: "muted small" },
            "Each channel's still appears at once. The videos then render in the background, one channel after another.") : null,
          error)),
      h("div", { class: "channel-grid" }, d.channels.map((c) => this.channelImageCard(c))));
  }

  /** For video posts: leave the sound out of the rendered videos (applies on the next render). */
  muteOption() {
    const hasSound = this.detail.video.audio;
    const box = h("input", { type: "checkbox", checked: hasSound && this.renderOptions.mute, disabled: !hasSound });
    box.addEventListener("change", () => { this.renderOptions.mute = box.checked; });
    return h("div", { class: "field" },
      h("label", { class: "check" }, box, h("span", {}, "Mute the videos")),
      h("span", { class: "muted small" }, hasSound
        ? "The posted videos have no sound. Takes effect when you render."
        : "This video has no sound."));
  }

  aoiEditor() {
    const { file, version, width, height } = this.detail.raw_image;
    const video = this.detail.video;
    const noun = video ? "video" : "photo";
    const scale = 1 + 2 * AOI_MARGIN;
    const frame = h("div", { class: "aoi-frame", title: "Drag to mark the area that must stay visible" });
    frame.style.aspectRatio = `${width} / ${height}`;
    // Square grid cells of a tenth of the photo's width, with lines through its corners, like the
    // terminal version. Sizes are fractions of the frame; a background-position percentage p puts the
    // tile at p * (frame - tile), hence the division.
    const cellX = 0.1 / scale;
    const cellY = cellX * (width / height);
    const offset = AOI_MARGIN / scale;
    frame.style.backgroundSize = `${cellX * 100}% ${cellY * 100}%`;
    frame.style.backgroundPosition = [cellX, cellY].map((cell) => cell < 1 ? `${(offset / (1 - cell)) * 100}%` : "0").join(" ");
    const rect = h("div", { class: "aoi-rect" });
    // A video plays in a loop, so the area can be checked against every moment of it
    frame.append(video
      ? loopingVideo(sessionFileUrl(this.name, video.file, video.version), sessionFileUrl(this.name, file, version), "aoi-photo")
      : h("img", { class: "aoi-photo", src: sessionFileUrl(this.name, file, version), alt: "", draggable: "false" }), rect);

    // Frame coordinates (0..1) <-> photo pixels; the photo sits in the middle of the margin
    const toPhoto = (event) => {
      const box = frame.getBoundingClientRect();
      const fx = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width));
      const fy = Math.min(1, Math.max(0, (event.clientY - box.top) / box.height));
      return [(fx * scale - AOI_MARGIN) * width, (fy * scale - AOI_MARGIN) * height];
    };
    const toPercent = (x, size) => ((x / size + AOI_MARGIN) / scale) * 100;
    const draw = (aoi) => {
      rect.hidden = !aoi;
      if (!aoi) return;
      const left = toPercent(aoi[0], width);
      const top = toPercent(aoi[1], height);
      rect.style.left = `${left}%`;
      rect.style.top = `${top}%`;
      rect.style.width = `${toPercent(aoi[2], width) - left}%`;
      rect.style.height = `${toPercent(aoi[3], height) - top}%`;
    };

    const note = h("p", { class: "muted small" });
    const describe = () => {
      note.textContent = this.renderOptions.aoi
        ? `Area set. ${video ? "Every frame is" : "Images are"} cropped around it (or fit whole when it covers most of the ${noun}).`
        : `Drag on the ${noun} to mark the area that must stay visible. The dark margin can be included to add space. Without an area the ${noun} is center-cropped.`;
    };

    let start = null;
    frame.addEventListener("pointerdown", (event) => {
      frame.setPointerCapture(event.pointerId);
      start = toPhoto(event);
    });
    frame.addEventListener("pointermove", (event) => {
      if (!start) return;
      const [x, y] = toPhoto(event);
      draw([Math.min(start[0], x), Math.min(start[1], y), Math.max(start[0], x), Math.max(start[1], y)]);
    });
    frame.addEventListener("pointerup", (event) => {
      if (!start) return;
      const [x, y] = toPhoto(event);
      const aoi = [Math.min(start[0], x), Math.min(start[1], y), Math.max(start[0], x), Math.max(start[1], y)].map(Math.round);
      start = null;
      // A tap without dragging keeps the previous area
      if (aoi[2] - aoi[0] > width * 0.02 && aoi[3] - aoi[1] > height * 0.02) this.renderOptions.aoi = aoi;
      draw(this.renderOptions.aoi);
      describe();
    });

    draw(this.renderOptions.aoi);
    describe();
    const clear = h("button", { class: "link-btn", onclick: () => { this.renderOptions.aoi = null; draw(null); describe(); } }, "Clear area");
    return h("div", { class: "aoi-editor" }, frame, note, clear);
  }

  channelImageCard(c) {
    const error = h("p", { class: "error", hidden: true });
    const act = (button, busy, path, json) => withButton(button, busy, async () => {
      this.update(await api(sessionUrl(this.name, `/channels/${encodeURIComponent(c.name)}${path}`), json ? { method: "PUT", json } : { json: {} }));
    }, error);

    const badges = [];
    if (!c.fits) badges.push(h("span", { class: "badge warn" }, "Headline too long"));
    if (c.image_outdated) badges.push(h("span", { class: "badge warn" }, "Text changed after rendering"));
    if (c.override.headline !== undefined) badges.push(h("span", { class: "badge" }, "Image headline edited"));
    if (c.override.font_size) badges.push(h("span", { class: "badge" }, `Font ${c.font_size} px (normally ${c.base_font_size})`));

    const actions = h("div", { class: "btn-row small-buttons" });
    if (!c.fits) {
      const shrink = h("button", { class: "btn" }, "Shrink font");
      shrink.addEventListener("click", () => act(shrink, "Shrinking...", "/shrink"));
      const shorten = h("button", { class: "btn" }, "Shorten with Gemini");
      shorten.addEventListener("click", () => act(shorten, "Asking Gemini...", "/shorten"));
      actions.append(shrink, shorten);
    }

    // The image headline can differ from the caption's (e.g. shorter); the caption keeps the full one
    const headlineInput = h("input", { type: "text", dir: "auto", value: c.headline });
    const useHeadline = h("button", { class: "btn" }, "Use on image");
    useHeadline.addEventListener("click", () => act(useHeadline, "Rendering...", "/override", { headline: headlineInput.value }));
    const editor = h("div", { class: "headline-editor", hidden: true },
      h("label", { class: "field" }, "Headline on this image", headlineInput),
      h("div", { class: "btn-row small-buttons" }, useHeadline));
    const editToggle = h("button", { class: "btn", onclick: () => { editor.hidden = !editor.hidden; } }, "Edit image headline");
    actions.append(editToggle);
    if (Object.keys(c.override).length) {
      const reset = h("button", { class: "btn" }, "Undo image changes");
      reset.addEventListener("click", () => act(reset, "Rendering...", "/override", {}));
      actions.append(reset);
    }

    let picture;
    if (this.detail.video) {
      picture = this.channelVideo(c);
    } else {
      picture = c.image
        ? h("a", { href: sessionFileUrl(this.name, c.image.file, c.image.version), target: "_blank", rel: "noopener" },
          h("img", { src: sessionFileUrl(this.name, c.image.file, c.image.version), alt: c.name, loading: "lazy" }))
        : h("div", { class: "no-image" }, "Not rendered yet");
    }
    const card = h("div", { class: "channel-card" },
      picture,
      h("div", { class: "channel-card-body" },
        h("div", { class: "channel-name" }, h("strong", {}, c.name), h("span", { class: "muted" }, ` · ${c.language}`)),
        badges.length ? h("div", { class: "badges" }, badges) : null,
        actions, editor, error));
    this.channelCards.set(c.name, card);
    return card;
  }

  /** True while the running video job still has this channel to render. */
  videoPending(c) {
    const job = this.jobs.get("videos");
    return Boolean(job && job.channels.includes(c.name) && !job.results[c.name]);
  }

  /** A video post's channel: its video once rendered, before that its still and how the render goes. */
  channelVideo(c) {
    const still = c.image ? sessionFileUrl(this.name, c.image.file, c.image.version) : null;
    if (c.video && !c.video_outdated && !this.videoPending(c)) {
      // Played by clicking it: the browser's controls would cover the headline at the bottom
      const video = h("video", { class: "channel-video", src: sessionFileUrl(this.name, c.video.file, c.video.version), poster: still,
        preload: "metadata", playsinline: true, loop: true, tabindex: 0, title: "Play or pause" });
      const mark = h("span", { class: "play-mark big" }, "▶");
      const toggle = () => (video.paused ? video.play() : video.pause());
      video.addEventListener("click", toggle);
      video.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          toggle();
        }
      });
      video.addEventListener("play", () => { mark.hidden = true; });
      video.addEventListener("pause", () => { mark.hidden = false; });
      return h("div", { class: "video-card" }, video, mark);
    }
    const status = h("div", { class: "render-status" });
    this.renderStatus.set(c.name, status);
    this.showRenderStatus(c, status);
    return h("div", { class: "video-pending" },
      still ? h("img", { src: still, alt: c.name, loading: "lazy" }) : h("div", { class: "no-image" }, "Not rendered yet"),
      status);
  }

  showRenderStatus(c, status) {
    const job = this.jobs.get("videos");
    if (this.videoPending(c)) {
      if (job.current === c.name) {
        const percent = Math.round(job.progress * 100);
        status.replaceChildren(h("span", {}, `Rendering the video... ${percent}%`), h("progress", { max: 100, value: percent }));
      } else {
        status.replaceChildren(h("span", {}, "Waiting to render the video"));
      }
      return;
    }
    if (!c.image) {
      status.replaceChildren();
      return;
    }
    // The last job's error stays on the card after the job has ended
    const last = job || this.lastVideoJob;
    const failed = last && last.results[c.name] && last.results[c.name].error;
    const render = h("button", { class: "btn" }, "Render video");
    const error = h("span", { class: "error", hidden: true });
    render.addEventListener("click", () => withButton(render, "Starting...", async () => {
      this.update(await api(sessionUrl(this.name, "/videos"), { json: { channels: [c.name] } }));
    }, error));
    status.replaceChildren(
      h("span", { class: failed ? "error" : "" },
        failed ? `The video failed: ${failed}` : c.video ? "The video is older than this still." : "No video yet."),
      render, error);
  }

  // ---------------------------------------------------------------- 3. captions
  renderCaptions() {
    const card = this.captionsCard;
    card.replaceChildren(
      h("p", { class: "muted small" }, "Telegram HTML: <b>bold</b>, <i>italic</i>, <a href=\"...\">links</a> and <tg-emoji> tags work. Changes are saved automatically."));
    for (const c of this.detail.channels) {
      const error = h("p", { class: "error", hidden: true });
      const head = h("div", { class: "channel-name" }, h("strong", {}, c.name), h("span", { class: "muted" }, ` · ${c.language}`));
      if (c.caption === null) {
        card.append(h("div", { class: "caption-block" }, head, h("p", { class: "warn" }, `No caption: there is no ${c.language}.md text.`)));
        continue;
      }
      const textarea = h("textarea", { rows: 8, dir: "auto" }, c.caption);
      const preview = h("div", { class: "caption-preview text", dir: "auto" });
      preview.append(sanitizeTelegramHtml(c.caption));
      const status = h("span", { class: "save-status" });
      const saver = autosave(() => api(sessionUrl(this.name, `/captions/${encodeURIComponent(c.name)}`), { method: "PUT", json: { text: textarea.value } }), status);
      this.savers.push(saver);
      textarea.addEventListener("input", () => {
        preview.replaceChildren(sanitizeTelegramHtml(textarea.value));
        saver.schedule();
      });
      textarea.addEventListener("blur", () => saver.flush());

      const rebuild = h("button", { class: "btn" }, "Rebuild from text");
      rebuild.addEventListener("click", () => {
        if (!confirm(`Replace the ${c.name} caption with one made from the current ${c.language} text? Your edits to this caption are lost.`)) return;
        withButton(rebuild, "Rebuilding...", async () => {
          this.update(await api(sessionUrl(this.name, `/captions/${encodeURIComponent(c.name)}/rebuild`), { json: {} }));
        }, error);
      });

      card.append(h("div", { class: "caption-block" },
        h("div", { class: "caption-head" }, head, status),
        c.caption_outdated ? h("p", { class: "warn small" }, "The text changed after this caption was made.") : null,
        h("div", { class: "caption-columns" },
          h("label", { class: "field" }, "Caption", textarea),
          h("div", { class: "field" }, h("span", { class: "muted small" }, "Preview"), preview)),
        h("div", { class: "btn-row small-buttons" }, rebuild),
        error));
    }
  }

  // ---------------------------------------------------------------- 4. publish
  async loadReviewChat() {
    if (!telegramReady() || !this.detail.review_channel || this.reviewChat) return;
    try {
      const shortcuts = await api("/api/telegram/shortcuts");
      const review = shortcuts.find((s) => s.label === "Review channel" && s.chat_id);
      if (review) this.reviewChat = { id: review.chat_id, name: review.name, photo: review.photo };
    } catch {
      /* the review channel name from channels.json is shown instead */
    }
    this.renderPublish();
    this.renderReviewSection();
  }

  /** The review chat, live, under the publish buttons while this post has previews in it
   *  (sent and not yet removed by publishing), so they can be checked without leaving the post. */
  renderReviewSection() {
    const section = this.reviewSection;
    const sendingPreviews = this.jobs.has("previews");
    const wanted = this.detail.review_channel && (this.detail.pending_previews > 0 || sendingPreviews);
    if (!wanted) {
      this.reviewPane = null;
      section.replaceChildren();
      return;
    }
    if (this.reviewPane) return; // built once; it updates itself
    if (!telegramReady()) {
      section.replaceChildren(h("p", { class: "muted small review-note" }, "The review chat appears here once Telegram is connected."));
    } else if (!this.reviewChat) {
      section.replaceChildren(h("p", { class: "muted small review-note" }, "Loading the review chat..."));
    } else {
      const { id, name, photo } = this.reviewChat;
      const box = h("div", { class: "messages review-messages" });
      this.reviewPane = new ChatPane(box);
      section.replaceChildren(
        h("div", { class: "review-head" },
          avatar(name, id, photo, "small"),
          h("div", { class: "title-text" }, h("strong", { dir: "auto" }, name), h("small", {}, "Review chat · updates live")),
          h("button", { class: "icon-btn", title: "Reload messages", onclick: () => this.reviewPane.reload() }, "⟳")),
        box);
      this.reviewPane.open(id);
    }
  }

  /** Scrolls the embedded review chat to a sent preview (it may still be arriving). */
  async showPreview(msgId) {
    if (!this.reviewPane.showMessage(msgId)) {
      await this.reviewPane.reload();
      this.reviewPane.showMessage(msgId);
    }
  }

  /** The published posts, one card per channel, each showing the post as it appears in that channel. */
  renderPublished() {
    const section = this.publishedSection;
    const posts = this.detail.channels.filter((c) => c.published && c.published.msg_id);
    if (!posts.length || !telegramReady()) {
      section.replaceChildren();
      this.publishedCards.clear();
      clearInterval(this.viewsTimer);
      this.viewsTimer = null;
      return;
    }
    // Keep the cards already shown; add new ones (a republished channel gets a new message ID)
    const cards = new Map();
    for (const c of posts) {
      const key = `${c.published.chat_id}/${c.published.msg_id}`;
      cards.set(key, this.publishedCards.get(key) || this.publishedCard(c));
    }
    this.publishedCards = cards;
    section.replaceChildren(
      h("h3", {}, "Published posts"),
      h("p", { class: "muted small" }, "Each post as it appears in its channel. Reactions update live, views every minute."),
      h("div", { class: "published-grid" }, [...cards.values()].map((entry) => entry.card)),
      // The Telegram tab opens with its chat list and nothing selected, ready for the next post
      h("div", { class: "start-over" },
        h("a", { class: "btn primary", href: "#/telegram" }, "Start over"),
        h("span", { class: "muted small" }, "Back to the Telegram chats to pick the messages for a new post.")));

    // View counts change without any Telegram update, so they are re-read now and then
    if (!this.viewsTimer) {
      this.viewsTimer = setInterval(() => {
        for (const { pane } of this.publishedCards.values()) pane.reload();
      }, 60000);
    }
  }

  publishedCard(c) {
    const { chat_id: chatId, msg_id: msgId } = c.published;
    const box = h("div", { class: "messages single-post" });
    const pane = new ChatPane(box);
    const avatarSlot = h("span", {});
    const title = h("div", { class: "title-text" }, h("strong", {}, c.name), h("small", {}, "Loading..."));
    const card = h("div", { class: "published-card" },
      h("div", { class: "review-head" }, avatarSlot, title,
        h("a", { class: "icon-btn", href: `#/telegram/${chatId}/${msgId}`, title: "Open in the Telegram tab" }, "↗")),
      box);
    pane.openMessage(chatId, msgId).then((info) => {
      if (!info) return;
      avatarSlot.replaceChildren(avatar(info.name, info.id, info.photo, "small"));
      title.replaceChildren(h("strong", { dir: "auto" }, info.name), h("small", {}, `${c.name} · ${c.language}`));
    });
    return { card, pane };
  }

  onTelegramStatus() {
    this.renderPublish();
    this.renderPublished();
    this.renderReviewSection();
    this.loadReviewChat();
  }

  onUpdate(update) {
    if (this.reviewPane) this.reviewPane.onUpdate(update);
    for (const { pane } of this.publishedCards.values()) pane.onUpdate(update);
  }

  /** Link to a sent message: previews scroll the review chat below, other posts open in the Telegram tab. */
  sentLink(chatId, msgId, label) {
    const link = h("a", { href: `#/telegram/${chatId}/${msgId}` }, label);
    if (this.reviewPane && this.reviewPane.id === chatId) {
      link.title = "Show it in the review chat below";
      link.addEventListener("click", (event) => {
        event.preventDefault();
        this.showPreview(msgId);
      });
    }
    return link;
  }

  sendResult(c, kind) {
    const job = this.jobs.get(kind);
    if (job && job.channels.includes(c.name)) {
      const result = job.results[c.name];
      if (!result) return h("span", { class: "muted" }, "sending...");
      if (!result.ok) return h("span", { class: "error" }, "failed");
      return this.sentLink(result.chat_id, result.msg_id, "✓ sent · view");
    }
    const logged = kind === "previews" ? c.preview : c.published;
    if (!logged) return h("span", { class: "muted" }, "—");
    const time = timeFormat.format(new Date(logged.date));
    if (logged.failed) return h("span", { class: "error" }, `failed ${time}`);
    if (logged.removed) return h("span", { class: "muted", title: "Deleted from the review channel after publishing" }, `✓ ${time} · removed`);
    return this.sentLink(logged.chat_id, logged.msg_id, `✓ ${time} · view`);
  }

  renderPublish() {
    if (!this.publishControls) return;
    const card = this.publishControls;
    const d = this.detail;
    const running = [...this.jobs.values()].find((j) => j.kind !== "videos" && j.status === "running");
    const error = h("p", { class: "error", hidden: true });
    card.replaceChildren();

    if (!telegramReady()) {
      card.append(h("p", { class: "warn" }, "Telegram isn't connected. ", h("a", { href: "#/setup" }, "Open Setup"), "."));
    }

    // A channel is ready with its image (a video post: its current video) and a caption
    const hasMedia = (c) => (d.video ? c.video && !c.video_outdated && !this.videoPending(c) : c.image);
    const isReady = (c) => hasMedia(c) && c.caption !== null;
    // "All channels" ticks every ready channel; half-ticked when only some are
    const readyNames = d.channels.filter(isReady).map((c) => c.name);
    const boxes = new Map();
    const allBox = h("input", { type: "checkbox", disabled: !readyNames.length || !!running });
    const syncAll = () => {
      const count = readyNames.filter((name) => this.chosenChannels.has(name)).length;
      allBox.checked = count > 0 && count === readyNames.length;
      allBox.indeterminate = count > 0 && count < readyNames.length;
    };
    allBox.addEventListener("change", () => {
      for (const name of readyNames) {
        if (allBox.checked) this.chosenChannels.add(name);
        else this.chosenChannels.delete(name);
        boxes.get(name).checked = allBox.checked;
      }
    });

    // Numbered in channels.json order, the order the server lists them in
    const rows = d.channels.map((c, i) => {
      const ready = isReady(c);
      const box = h("input", { type: "checkbox", checked: ready && this.chosenChannels.has(c.name), disabled: !ready || !!running });
      if (ready) boxes.set(c.name, box);
      box.addEventListener("change", () => {
        if (box.checked) this.chosenChannels.add(c.name);
        else this.chosenChannels.delete(c.name);
        syncAll();
      });
      return h("tr", {},
        h("td", { class: "row-number" }, i + 1),
        h("td", {}, h("label", { class: "check" }, box, h("span", {}, c.name), h("span", { class: "muted" }, ` · ${c.language}`)),
          ready ? null : h("div", { class: "muted small" }, hasMedia(c) ? "no caption" : d.video ? "video not rendered yet" : "not rendered yet"),
          c.has_target ? null : h("div", { class: "warn small" }, "no chat_id in channels.json")),
        h("td", {}, this.sendResult(c, "previews")),
        h("td", {}, this.sendResult(c, "published")));
    });
    syncAll();

    const chosen = () => d.channels.filter((c) => this.chosenChannels.has(c.name) && isReady(c)).map((c) => c.name);
    const send = (kind, button, busy) => withButton(button, busy, async () => {
      const channels = chosen();
      if (!channels.length) throw new Error("Tick at least one channel.");
      if (kind === "published" && !confirm(
        `Publish to ${channels.length} LIVE channel${channels.length > 1 ? "s" : ""}?\n\n${channels.join("\n")}\n\n`
        + "After publishing, their previews are deleted from the review channel.")) return;
      const job = await api(sessionUrl(this.name, "/send"), { json: { kind, channels } });
      this.jobs.set(kind, job);
      this.renderPublish();
      this.renderReviewSection(); // sending previews brings up the review chat
    }, error);

    const reviewName = this.reviewChat ? this.reviewChat.name : d.review_channel;
    const sendable = telegramReady() && !running;
    const previewButton = h("button", { class: "btn", disabled: !sendable || !d.review_channel }, "Send previews");
    previewButton.addEventListener("click", () => send("previews", previewButton, "Starting..."));
    const publishButton = h("button", { class: "btn danger", disabled: !sendable }, "Publish to live channels");
    publishButton.addEventListener("click", () => send("published", publishButton, "Starting..."));

    card.append(
      h("p", { class: "muted small" },
        d.review_channel
          ? ["Previews go to the review channel (", h("bdi", {}, reviewName), ") and appear below, with your colleagues' reactions. "
            + "Publishing deletes the published channels' previews from it."]
          : "No review channel is set in channels.json, so previews are off."),
      h("table", { class: "publish-table" },
        h("thead", {}, h("tr", {}, h("th", { class: "row-number" }, "#"), h("th", {}, h("label", { class: "check" }, allBox, h("span", {}, "All channels"))), h("th", {}, "Preview"), h("th", {}, "Live"))),
        h("tbody", {}, rows)),
      running ? h("p", { class: "muted" },
        `${running.kind === "previews" ? "Sending previews" : "Publishing"}: ${Object.keys(running.results).length} of ${running.channels.length} done. `
        + "Posts are spaced a few seconds apart to stay within Telegram's limits.") : "",
      error,
      h("div", { class: "btn-row" }, previewButton, publishButton));
  }

  onJob(job) {
    if (job.session !== this.name) return;
    if (job.kind === "videos") {
      this.onVideoJob(job);
      return;
    }
    this.jobs.set(job.kind, job);
    this.renderPublish();
    // A preview was just sent: show it in the review chat (also when Telegram sends no update for our own posts)
    if (job.kind === "previews" && this.reviewPane) {
      this.reviewPane.onUpdate({ type: "new", chat_id: this.reviewPane.id, ids: [] });
    }
    if (job.status !== "running") {
      if (job.status === "failed") alert(`Sending stopped: ${job.error}`);
      if (job.cleanup_error) alert(`Published. ${job.cleanup_error}`);
      this.jobs.delete(job.kind);
      // The publish log now has the results: published posts appear, removed previews leave the review chat.
      // Telegram sends no update for our own deletions, so a review chat that stays is loaded afresh.
      this.reload().then(() => {
        if (job.kind === "published" && job.previews_removed && this.reviewPane) this.reviewPane.open(this.reviewPane.id);
      });
    }
  }

  /** Video render progress. Only the cards change, so the area editor keeps playing. */
  async onVideoJob(job) {
    if (job.status === "replaced") return; // a newer job took over; its events follow
    const known = this.jobs.get("videos");
    const before = known && known.id === job.id ? Object.keys(known.results) : [];
    const finished = Object.keys(job.results).filter((name) => !before.includes(name));
    this.lastVideoJob = job;
    if (job.status === "running") this.jobs.set("videos", job);
    else this.jobs.delete("videos");
    if (job.status === "failed") alert(`Rendering the videos stopped: ${job.error}`);

    if (!finished.length && job.status === "running") {
      for (const c of this.detail.channels) {
        const status = this.renderStatus.get(c.name);
        if (status && status.isConnected) this.showRenderStatus(c, status);
      }
      return;
    }
    // A channel is done: its card shows the new video, and it can be ticked for publishing
    this.detail = await api(sessionUrl(this.name));
    for (const c of this.detail.channels) {
      const card = this.channelCards.get(c.name);
      if (card && card.isConnected && (finished.includes(c.name) || job.status !== "running")) card.replaceWith(this.channelImageCard(c));
      const status = this.renderStatus.get(c.name);
      if (status && status.isConnected) this.showRenderStatus(c, status);
    }
    this.renderPublish();
  }
}
