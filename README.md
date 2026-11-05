# VTP: Vazirified Telegram Publisher

Turns one news item (text plus a photo or a video) into branded image or video posts with captions and publishes them to several Telegram channels in English, Persian, Arabic and Kurdish (Sorani).

There are two ways to use it. Both do the same work, on the same files:

- **Web interface** (recommended): runs in a browser on the same device, including the phone's own browser when VTP runs in Termux on Android. You pick the source messages straight from your Telegram chats, check and fix every step on one page, and watch the previews, your colleagues' reactions and the published posts without leaving it. See [Web interface](#web-interface).
- **Terminal + window interface**: the original version, a Tkinter window followed by terminal prompts. See [Terminal interface](#terminal-interface).

## Contents

- [How it works](#how-it-works)
- [Setup](#setup)
- [First run](#first-run)
- [Web interface](#web-interface)
  - [Starting it](#starting-it)
  - [Publishing a post](#publishing-a-post)
  - [The Telegram tab](#the-telegram-tab)
  - [The Setup tab](#the-setup-tab)
  - [Good to know](#good-to-know)
- [Terminal interface](#terminal-interface)
- [Configuration reference](#configuration-reference)
- [Tools](#tools)
- [Common tasks](#common-tasks)
- [Project layout](#project-layout)

## How it works

Every post goes through four steps:

1. **Source:** the news text (it may already contain some languages) and one photo or video, picked from your Telegram chats, pasted, or uploaded.
2. **Text** (`text_engine.py`): Gemini splits and translates the text into every channel language. Existing human translations in the input are kept as-is.
3. **Graphics** (`image_engine.py`): for each channel, the photo is placed on a blurred background, the channel template is overlaid, and the headline is drawn. For a video (`video_engine.py`), every frame is laid out the same way and encoded with ffmpeg.
4. **Publishing** (`publisher.py`): builds a caption for each channel, sends previews to the review channel, then posts to the live channels after you approve.

Each post is one session folder, `_workspace/session_<timestamp>_<slug>/`, containing:

| File | Created by | Contents |
|---|---|---|
| `<lang>.md` | Text | `# Headline` on the first line, then the body |
| `raw_image.<ext>` | Source | Copy of the chosen photo |
| `<channel>_broadcast.jpg` | Graphics | Final image for each channel (for a video post: its still, also the video's thumbnail) |
| `raw_video.<ext>`, `video_frame.png`, `video_preview.mp4`, `video_info.json` | Source (video posts) | The chosen video, the frame used for the stills, a small copy the browser plays, and its details (duration, size) |
| `<channel>_broadcast.mp4` | Graphics (video posts) | Final video for each channel |
| `<channel>_caption.txt` | Publishing | Final caption (HTML) for each channel |
| `web_render.json`, `web_publish_log.json` | Web interface | Render settings, and where previews and posts were sent (only for posts handled in the browser; the terminal interface ignores them) |

## Setup

| Platform | Command |
|---|---|
| Windows | `setup.bat` |
| Linux | `bash setup.sh` |
| Android (Termux) | move the project to `~/vtp---vazirified-telegram-publisher`, then `bash setup-termux.sh` |

Each script creates `.venv` and installs the packages in `requirements.txt`.
- `setup.bat` also installs Python 3.12 if none is found.
- `setup-termux.sh` also installs the compilers Termux needs, plus Tkinter and X11 for the terminal interface. The web interface doesn't need X11.

**ffmpeg** renders video posts. On Windows and Linux it comes with the `imageio-ffmpeg` package (about 100 MB). On Termux, `setup-termux.sh` installs it with `pkg install ffmpeg` (and `run-web.sh` does if it's missing). Photo posts don't need it.

**FriBiDi** is needed for correct Kurdish headlines (Pillow's Raqm text layout):
- Windows: bundled in `kernel/lib/`; nothing to install.
- Linux and Termux: the setup scripts install it and report at the end whether Raqm is active.

Without it the app still runs, but Kurdish ڵ ڕ ێ are drawn without their V mark, and a warning is printed when images are rendered. The web interface's Setup tab shows whether Raqm is active.

### Local files (not in git)

`_config/`, `_credentials/` and `_workspace/` are ignored by git. A fresh clone needs:

| Path | What it is | How to get it |
|---|---|---|
| `_credentials/telegram_api.json` | `{"api_id": 1234567, "api_hash": "..."}` | Create an app at https://my.telegram.org, then enter the values on the web interface's Setup tab (or create the file by hand) |
| `_credentials/user_session.session` | Telethon login session | Created on first login (see [First run](#first-run)) |
| `_credentials/gemini_keys.json` | Gemini API key and last used model | Created when you save your key (see [First run](#first-run)) |
| `_config/channels.json` | Channel settings | Copy from an existing install, or create with the [configurator](#configurator) |
| `_config/fonts/` | Fonts named in `channels.json` (Dana) | Copy from an existing install |
| `_config/templates/` | One overlay PNG per channel | Copy from an existing install |

## First run

**With the web interface** (easiest, also on a phone):
1. Start it (see [Starting it](#starting-it)). The browser opens on the **Telegram** tab, which links to **Setup** while Telegram isn't connected.
2. On **Setup**, enter the Telegram API ID and hash if they're asked for, then log in: phone number with country code, the login code Telegram sends you, and your two-step verification password if you have one.
3. Paste your Gemini API key from Google AI Studio and tap **Save key**.

**With the terminal:**
1. **Log in to Telegram once.** Telethon asks for your phone number, the login code Telegram sends you, and your 2FA password if you have one. Do this first with the emoji inspector, because a login prompt that appears during the GUI is hard to answer:
   ```bash
   python kernel/inspect-emoji.py
   ```
   Activate `.venv` first: `.venv\Scripts\activate` on Windows, `source .venv/bin/activate` on Linux/Termux. Enter `me` when it asks for a channel. The session is saved to `_credentials/user_session.session`.
2. **Gemini API key.** The first time the text phase runs, it asks you to paste a key from Google AI Studio. It's saved to `_credentials/gemini_keys.json`.

Both interfaces use the same login and key, so this is needed only once.

## Web interface

### Starting it

| Platform | Command |
|---|---|
| Windows | `run-web.bat` |
| Linux / Termux | `bash run-web.sh` |

- It starts a server at `http://127.0.0.1:8765/` and opens it in the default browser (on Android, the phone's browser). Add `--port 9000` to use another port, or `--no-browser` to skip opening it.
- Keep the terminal window open while you work; press Ctrl+C in it to stop the server.
- On Termux, the launcher keeps Android from suspending the server while the screen is off.
- If `.venv` lacks a package the web interface needs (e.g. it was created before the web interface or video posts existed), the launcher installs the missing packages first.

The page has three tabs:

| Tab | For |
|---|---|
| **Telegram** | Your chats, live: read messages, see reactions and who reacted, react, and select messages to start a post |
| **Posts** | All posts, newest first, and each post's steps: texts, images, captions, publishing |
| **Setup** | Telegram login, Gemini key, and checks for `channels.json` and Raqm |

A green dot at the top right means Telegram is connected.

### Publishing a post

**1. Pick the source in the Telegram tab.**
Open the chat with the news and tap the messages with the text and the photo or video. An album counts as one message. Select mode is on by default, so a tap selects instead of opening links or photos. A bar shows what's selected, with **Clear** and **Start post**.

To start without Telegram, open **Posts → New post** and paste the text instead.

**2. New post page.**
- **Text:** check it and edit if needed; it's what Gemini receives. The selected messages are joined in chat order. Languages already in the text are kept as they are; missing ones are translated.
- **Photo or video:** tap the one to use (photos and videos from the selected messages are offered; videos have a ▶ mark), or **Upload a photo or video**, which opens the gallery or camera on a phone. Photos: JPG, PNG, WebP or AVIF up to 30 MB. Videos: any common format (MP4, MOV, MKV, WebM, AVI, ...) up to 2 GB, including Telegram "GIFs" and round videos.
- **Translate:** choose the Gemini model and tap **Translate and create post**. A video is prepared first (a still frame and a small copy the browser can play), which takes a while for long videos. Translating can take up to a minute. If the model fails or is overloaded, the error is shown and your text and photo or video stay: choose another model and try again (the video isn't prepared again).

The post page then opens. Its four sections can be revisited in any order; changes are saved automatically. Tap a section's heading to fold it away or open it again. Captions start folded; the browser remembers which sections you last left open, for every post.

**3. Texts.** Each language's headline and body, with English first. The headline is drawn on the images; the captions are made from the headline and the body.

**4. Images.**
- Optionally drag a box on the photo to mark the area that must stay visible. The dark grid around the photo can be included to add space around it; its squares are a tenth of the photo's width, as in the terminal version. If the area covers most of the photo, it's fitted whole; otherwise the photo is cropped around it. **Clear area** goes back to center-cropping.
- Set the **background blur** with the slider and tap **Render images**. Every channel's image appears in a grid; tap one to open it full size.
- A channel whose headline doesn't fit is marked **Headline too long**, with two fixes:
  - **Shrink font** lowers the font size 2 px at a time until it fits, down to about 18 px.
  - **Shorten with Gemini** asks for a shorter headline.
- **Edit image headline** sets a different headline for one image only; **Undo image changes** goes back to the text's headline. Captions always keep the full headline.
- When a text is edited after rendering, its images are marked **Text changed after rendering**; render again.

**4. Video** (video posts, instead of Images). It works like Images, with these differences:
- The area editor plays the video muted in a loop, so you can check the area against every moment of it. HDR videos (e.g. from iPhones) are shown, and rendered, with normal colours.
- **Render** shows every channel's still at once, so the headline fixes above can be done right away. The videos then render in the background, one channel after another; each card shows **Waiting to render the video** or **Rendering the video... N%**, then the video (click it to play or pause). You can keep working on the page meanwhile.
- A headline fix on one channel re-renders only that channel's video. Rendering again while videos are rendering restarts with the new settings.
- A card whose video failed or is older than its still has **Render video**.
- **Mute the videos** (under the blur slider) leaves the sound out of the posted videos; like the blur, it takes effect when you render. It's greyed out when the video has no sound.
- Videos are H.264 MP4 at the template's size, with the original sound unless muted. On a PC a one-minute clip takes roughly 15 seconds per channel; on a phone several times longer.

**5. Captions.** One editor per channel with a preview of how Telegram will show it. Captions are Telegram HTML: `<b>`, `<i>`, `<a href="...">` and `<tg-emoji>` tags work. When a text changed after its caption was made, the caption is marked, and **Rebuild from text** recreates it (discarding your edits to that caption).

**6. Publish.**
1. Tick the channels to send; none are ticked at first. The channels are numbered in `channels.json` order, and **All channels** in the table header ticks or unticks every channel that has its image (or current video) and a caption; it shows half-ticked when only some are ticked. For a video post, a channel can be ticked once its video is rendered and up to date, and sending waits until all of the post's videos have rendered.
2. Tap **Send previews**. The posts go to the review channel (`catch_all_channel`), a few seconds apart to stay within Telegram's limits. Each row shows its progress, then a **view** link.
3. The review chat then appears below the buttons, live: the previews arrive in it, with your colleagues' reactions and who reacted. A preview's **view** link scrolls to it.
4. Tap **Publish to live channels** and confirm. Each ticked channel gets its post at its `chat_id`, again a few seconds apart. Video posts go out as streamable Telegram videos with the caption, using the channel's still as the thumbnail; uploading them takes longer than photos.
5. After publishing, the previews of the channels that were published are **deleted from the review channel**: every preview VTP sent for them, and nothing else. If Telegram refuses (for example, no right to delete messages in a review *channel*), a message says so and the posts stay published.
6. **Published posts** appear as cards, one per channel, each showing the post as it looks in its channel. Reactions update live and views every minute; **↗** opens the post in the Telegram tab. While some previews remain, the review chat stays below the cards; it disappears once everything is published.
7. **Start over** under the cards goes back to the Telegram tab's chat list, with nothing selected, to pick the next news item.

You can leave a post at any step and come back later from **Posts**, for example to fix a caption and send its preview again.

### The Telegram tab

- **Shortcuts** at the top: the review channel and every channel in `channels.json`. A channel ID that can't be found is listed with the reason. **Chats** below lists all your chats, with **Load more** for older ones.
- Chats show their profile pictures, unread counts, and a red **♥** badge when there are reactions to your messages that you haven't seen yet.
- Messages show photos, albums, formatting, views and reactions. New, edited and deleted messages, and reaction changes, appear live.
- **Reactions:**
  - Each reaction shows its count; your own is outlined.
  - In groups and private chats, the names of the people who reacted are shown, with reactions you haven't seen yet in bold. **Who reacted** loads the full list. In channels, Telegram keeps reactions anonymous, so only counts are shown.
- **Reacting:**
  - Tap **☺+** under a message for the picker: your recent reactions (the same list the Telegram apps show), and **More** for all of them.
  - Tapping a reaction under a message reacts with it; tapping your own removes it. A message gets one reaction from you; choosing another replaces it.
  - The picker only offers what the chat allows, and custom emoji only with Telegram Premium. Reacting works the same in the review chat and the published-post cards on a post page.
- **Select mode** is on by default: tapping a message selects it for a new post, while buttons such as **☺+** and **Who reacted** still work. Tap **Select ✓** in the chat header to turn it off, so photos open full size and links can be followed; it stays off until the page is reloaded.
- Reading here doesn't mark messages or reactions as read. Your reactions are the only thing this tab changes on Telegram.

### The Setup tab

- **Telegram:** API ID and hash (when `_credentials/telegram_api.json` is missing), login with phone, code and two-step verification password, and the account you're logged in as. To switch accounts, stop the server and delete `_credentials/user_session.session`.
- **Gemini:** whether a key is saved and the last used model; paste a new key to replace it.
- **Rendering and channels:** how many channels `channels.json` has, and whether Raqm is active.

### Good to know

- **One program at a time.** The Telegram session can be used by only one program at once. Close `run.bat`/`run.sh`, `publisher.py` and `inspect-emoji.py` while the web interface runs, and the other way round. If Setup reports `database is locked`, close the other program and tap **Try again**.
- **Only this device can connect.** The server listens on `127.0.0.1` and refuses requests addressed to any other host name or sent from other websites.
- **Same files as the terminal.** A post is an ordinary session folder, so the terminal tools work on it too, and images and captions are identical whichever interface made them. This includes video posts: one made in either interface can be continued in the other (the area, blur and mute you chose aren't shared, as with photos).
- **Cache.** Images shown in the browser (photos, profile pictures, custom emoji) are cached in `_workspace/web_cache/`, and photos and videos chosen for a new post in `_workspace/web_uploads/`. Both are deleted after 7 days; a post keeps its own copy of its photo or video.

## Terminal interface

| Platform | Command |
|---|---|
| Windows | `run.bat` |
| Linux / Termux | `bash run.sh` (on Termux, start the Termux:X11 app first) |

`kernel/main.py` runs the four steps in order: an ingestion window, then terminal prompts for the text, graphics and publishing phases.

**Launcher behavior:**
- If `.venv` is missing, it offers to run setup first.
- It starts the pipeline automatically: after 3 seconds on Windows, 5 on Linux. Press `N` instead to get a shell with `.venv` active.
- After each run it starts again automatically after 5 seconds. Press `N` to exit.

Many prompts have a timeout and continue with the default shown in brackets, so the pipeline can run with almost no typing.

### 1. Ingestion window

**Source text:** paste it, or click **Fetch Text from Telegram**:
1. Pick a chat. Double-click it or use **View Contents**. **Load More** pages back through older chats.
2. Select messages. With **Easy Multi-Select** ticked, each click toggles a row, so no Ctrl is needed.
3. Click **Insert Selected**. The messages are added to the text box in list order (newest first), separated by blank lines.

The text may already contain some languages. Each language block should start with its headline as the first line or paragraph. Missing languages are translated from English, and English is generated first if it's missing.

**Image or video:** click **Browse Local...** (PNG/JPG photos, or a video: MP4, MOV, MKV, WebM, AVI, ...), or **Fetch from Telegram**:
1. Pick a chat.
2. Select a row marked `📎 MEDIA`. Text-only rows can't be selected.
3. Click **Download & Use**. The file is saved in `_workspace/`.

A video makes a video post. It's checked when the pipeline starts (an unreadable file stops the run before Gemini is asked), and after the text phase it's prepared: `[~] Preparing the video... N%` makes its still frame and a small copy for the area window.

Click **Start Processing Pipeline** when both are set. Closing the window cancels the run.

### 2. Text phase (terminal)

1. **Model menu:** lists the Gemini models currently available. Type a number, or press Enter (or wait 5 s) to reuse the last model.
2. If the model fails or returns bad data, the menu appears again. Your text is kept. Press Ctrl+C to abort.

### 3. Graphics phase (terminal)

1. **`Define manual AOI? (y/n)`** (default `n` after 5 s):
   - `y` opens the photo surrounded by a dark grid. Click two opposite corners of the area that must stay visible. The corners can extend into the grid to add margin. A video plays there in a loop, silently, so the area can be checked against all of it.
   - If the area covers more than 60% of the photo, it's fitted whole into the photo slot. Otherwise the photo is cropped around the area's center.
   - Without an area, the photo is center-cropped.
2. **`Enter background blur radius`** (default `30` after 5 s): the blur of the full-canvas background made from the same photo.
   - For a video with sound, **`Mute the videos? (y/n)`** follows (default `n` after 5 s): `y` leaves the sound out of every channel's video.
3. **Overflow menu**, shown for each channel whose headline doesn't fit its safe area (too many lines or too tall):
   - `1` shrinks the font 2 px at a time, down to 18 px. It draws at 18 px even if the text still doesn't fit.
   - `2` asks Gemini for a shorter headline, then checks again. This is the default after 5 s.
   - `3` lets you type the headline yourself.

   The shortened headline is used only for the image. The caption keeps the full headline from `<lang>.md`.
4. **Videos** (video posts): after every channel's still, each channel's video is rendered with the same area, blur and headline, shown as `[~] Rendering video for <channel>... N%`. A one-minute clip takes roughly 15 seconds per channel on a PC.

### 4. Publishing phase (terminal)

1. **Caption files:** `<channel>_caption.txt` is created for every channel that doesn't have one yet:
   ```
   <header> <b><headline></b>

   <body>

   <footer>
   ```
   Existing caption files are never overwritten, so manual edits are kept.
2. **`Select channels`**: type numbers from the list separated by commas (e.g. `1,3,4`), or `A` for all. The list is sorted alphabetically.
3. **Previews:** each selected channel's image and caption go to the review channel (`catch_all_channel`), 3–8 seconds apart.
4. **Review menu:**
   - `A` **Approve:** posts to each channel's `chat_id`, 5–10 seconds apart.
   - `R` **Retry:** reloads the images and captions from disk and sends the previews again. Edit a caption file or re-render an image first, then press `R`.
   - `S` **Stall:** exits without posting anything live.

   The terminal interface doesn't delete previews after publishing; the web interface does.

## Configuration reference

### `_config/channels.json`

```json
{
  "catch_all_channel": "me",
  "channels": {
    "persian_broker": {
      "chat_id": "@your_channel",
      "language": "fa",
      "is_rtl": true,
      "image_layout": {
        "canvas_size": [1000, 1000],
        "raw_image_placement": { "x": 10, "y": 10, "width": 980, "height": 660 },
        "template_overlay_path": "_config/templates/brokers_fa.png",
        "headline_safe_area": {
          "x_start": 36, "y_start": 700, "width": 930, "max_height": 195,
          "font_path": "_config/fonts/Dana-Medium.ttf", "font_size": 48,
          "font_color": "#ffffff", "alignment": "center",
          "line_spacing": 1.1, "max_lines": 2
        }
      },
      "caption_settings": {
        "header_template": "",
        "footer_template": "\\n\\n<a href=\"https://example.com\">Visit us</a>"
      }
    }
  }
}
```

| Key | Meaning |
|---|---|
| `catch_all_channel` | Where previews go: `me` (Saved Messages), `@username`, or a numeric ID. Empty means no previews; the review menu still appears in the terminal. For the web interface's automatic preview deletion, use a chat where your account may delete its own messages (Saved Messages, a group, or a channel where you're an admin with delete rights). |
| `chat_id` | The live channel: `@username` or a numeric ID such as `-1001234567890`. Numeric strings are converted to numbers automatically. |
| `language` | `en`, `fa`, `ar` or `ckb`. It selects `<lang>.md` and the language Gemini translates into. Channels can share a language. |
| `is_rtl` | `true` for Persian, Arabic and Kurdish. Turns on right-to-left shaping. |
| `canvas_size` | Output image size in pixels. It must equal the template's pixel size, or rendering fails. The configurator sets it from the template automatically. |
| `raw_image_placement` | Where the photo goes on the canvas: `x`, `y`, `width`, `height`. |
| `template_overlay_path` | PNG drawn over the photo, relative to the project root. Transparent areas show the photo. |
| `headline_safe_area` | The box the headline must fit in: `x_start`, `y_start`, `width`, `max_height`. The text is centered vertically inside it. |
| `font_path`, `font_size`, `font_color` | Headline font, relative to the project root. The size is the starting size before any shrinking. |
| `alignment` | `left`, `center` or `right`. Defaults to `right` for RTL and `left` otherwise. |
| `line_spacing`, `max_lines` | Line height multiplier, and the most lines allowed before a headline counts as too long. |
| `header_template`, `footer_template` | Caption HTML placed before the headline and after the body. Write `\n` for a line break. Telegram HTML tags work, including custom emoji (see [Emoji inspector](#emoji-inspector)). |

Older files may also contain `resize_mode` and `font_weight`. Nothing reads them: the photo is always cover-fitted, and the font weight comes from the font file you pick (e.g. `Dana-Bold.ttf`). The configurator drops them when you edit a channel.

## Tools

Run these with `.venv` active, from the project root. Like the terminal interface, they can't run while the web interface is running (shared Telegram session).

### Configurator

```bash
python kernel/configurator.py
```

A terminal menu for editing `_config/channels.json`:

| Option | Does |
|---|---|
| `1` Add a New Channel | Asks for an internal name (e.g. `persian_tv`), then every setting below |
| `2` Edit an Existing Channel | Lists channels, then asks every setting again with the current value as default |
| `3` Delete a Channel | Removes a channel by internal name |
| `4` View Active Channels | Shows each channel's target and language, plus the review channel |
| `5` Configure Global Catch-All Review Gate | Sets `catch_all_channel`: `me`, an `@username` or a numeric ID. `off` disables previews; Enter keeps the current value. |
| `0` Save & Exit | Writes the file. **Changes are only saved here.** Ctrl+C discards them. |

**Answering the prompts:**
- Each prompt shows its default in brackets; press Enter to keep it.
- Yes/no fields accept `true`, `t`, `y`, `yes` or `1`. Anything else means no.
- For header and footer templates, type `\n` literally for a line break.

**Prompts, in order:**
1. Chat ID, language, RTL.
2. Photo placement: X, Y, width, height.
3. Template: pick a number from the PNGs in `_config/templates/`, or type a path. A new channel has no default, so you must choose one. The canvas size is then set to the template's size.
4. Safe area: X, Y, width, max height.
5. Font: pick a number from the fonts in `_config/fonts/`, or type a path. The default is the current font, or `Dana-Medium.ttf` for a new channel.
6. Font size, color, alignment, line spacing, max lines.
7. Header and footer templates.

A template or font must be an existing file. To add a new one, copy it into `_config/templates/` or `_config/fonts/` first.

### Emoji inspector

```bash
python kernel/inspect-emoji.py
```

Logs in to Telegram and asks for a chat: `@username`, or `me` for Saved Messages. For each of the last 10 messages that has text, it prints:
- the text as Markdown and as HTML, with formatting and custom emoji as tags;
- any reactions, with custom emoji IDs and ready-to-paste tags such as `<tg-emoji emoji-id="1234567890123456789">🌐</tg-emoji>`.

**To use a custom emoji in a caption template:**
1. Send a message containing it to Saved Messages.
2. Run the inspector with `me`.
3. Copy its `<tg-emoji ...>` tag from the HTML output into `header_template` or `footer_template`.

### Running one phase on its own

Each of these works on the **latest** session folder:

| Command | Does |
|---|---|
| `python kernel/image_engine.py` | Re-renders every channel image (overwrites `*_broadcast.jpg`), and for a video post every channel's video (`*_broadcast.mp4`) |
| `python kernel/publisher.py` | Creates any missing captions, then runs channel selection, previews and review. Sends a video post's rendered videos |

`python kernel/text_engine.py` is a developer test. It sends a built-in sample text to Gemini and creates a new session folder.

## Common tasks

**Fix a translation:**
- *Web:* edit the text on the post page, **Render images again**, then **Rebuild from text** on the captions marked as changed.
- *Terminal:*
  1. Edit `<lang>.md` in the session folder.
  2. Run `python kernel/image_engine.py` if the headline changed.
  3. Delete that language's `*_caption.txt` files so they're rebuilt from the `.md`, or edit them directly.
  4. Run `python kernel/publisher.py`.

**Change one caption only:**
- *Web:* edit it in the Captions section, then **Send previews** for that channel.
- *Terminal:* edit `<channel>_caption.txt`, then press `R` in the review menu.

**Fix a headline that renders badly:**
- *Web:* **Edit image headline** on that channel's image, or edit the headline in Texts and render again.
- *Terminal:* edit the first line of `<lang>.md`, then re-render with `python kernel/image_engine.py`.

**Test without posting live:**
- *Web:* send previews only, and don't tap **Publish to live channels**.
- *Terminal:* keep `catch_all_channel` set to `me` and answer `S` at the review menu.

## Project layout

```
kernel/
  main.py              Terminal interface: orchestrator and ingestion window
  text_engine.py       Gemini translation -> <lang>.md
  image_engine.py      Image rendering and headline layout
  video_engine.py      Video posts: the same layout on every frame, with ffmpeg
  publisher.py         Captions, previews, review, live posting
  auth_manager.py      Telegram client from _credentials/
  common.py            Shared paths, config loading, Gemini helpers
  configurator.py      Channel settings editor
  inspect-emoji.py     Message/emoji inspector
  webapp.py            Web interface server (FastAPI)
  telegram_service.py  Web interface: Telegram login, chats, reactions, live updates
  pipeline_service.py  Web interface: posts (session folders), using the engines above
  web/                 Web interface page: app.js (Telegram tab, Setup), posts.js (Posts tab)
  lib/                 FriBiDi for Windows (see lib/README.txt)
requirements.txt       Python packages
setup.*                Setup scripts per platform
run-web.*              Web interface launchers
run.*                  Terminal interface launchers
```
