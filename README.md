# VTP: Vazirified Telegram Publisher

Turns one news item (text plus a photo) into branded image posts with captions and publishes them to several Telegram channels in English, Persian, Arabic and Kurdish (Sorani).

## Contents

- [How it works](#how-it-works)
- [Setup](#setup)
- [First run](#first-run)
- [Web interface](#web-interface)
- [Running the pipeline](#running-the-pipeline)
- [Configuration reference](#configuration-reference)
- [Tools](#tools)
- [Common tasks](#common-tasks)
- [Project layout](#project-layout)

## How it works

`kernel/main.py` runs four phases in order:

1. **Ingestion** (Tkinter window): paste the source text or pick messages from your Telegram chats, then choose a local image or download one from a chat.
2. **Text** (`text_engine.py`): Gemini splits and translates the text into every channel language. Existing human translations in the input are kept as-is.
3. **Graphics** (`image_engine.py`): for each channel, the photo is placed on a blurred background, the channel template is overlaid, and the headline is drawn.
4. **Publishing** (`publisher.py`): builds a caption for each channel, sends previews to the review channel, then posts to the live channels after you approve.

Each run creates one session folder, `_workspace/session_<timestamp>_<slug>/`, containing:

| File | Created by | Contents |
|---|---|---|
| `<lang>.md` | Text | `# Headline` on the first line, then the body |
| `raw_image.<ext>` | Ingestion | Copy of the chosen photo |
| `<channel>_broadcast.jpg` | Graphics | Final image for each channel |
| `<channel>_caption.txt` | Publishing | Final caption (HTML) for each channel |

## Setup

| Platform | Command |
|---|---|
| Windows | `setup.bat` |
| Linux | `bash setup.sh` |
| Android (Termux) | move the project to `~/vtp---vazirified-telegram-publisher`, then `bash setup-termux.sh` |

Each script creates `.venv` and installs the packages in `requirements.txt`.
- `setup.bat` also installs Python 3.12 if none is found.
- `setup-termux.sh` also installs the compilers, Tkinter and X11 pieces Termux needs. Start the Termux:X11 app before running the pipeline.

**FriBiDi** is needed for correct Kurdish headlines (Pillow's Raqm text layout):
- Windows: bundled in `kernel/lib/`; nothing to install.
- Linux and Termux: the setup scripts install it and report at the end whether Raqm is active.

Without it the app still runs, but Kurdish ڵ ڕ ێ are drawn without their V mark, and a warning is printed when images are rendered.

### Local files (not in git)

`_config/`, `_credentials/` and `_workspace/` are ignored by git. A fresh clone needs:

| Path | What it is | How to get it |
|---|---|---|
| `_credentials/telegram_api.json` | `{"api_id": 1234567, "api_hash": "..."}` | Create an app at https://my.telegram.org |
| `_credentials/user_session.session` | Telethon login session | Created on first login (see [First run](#first-run)) |
| `_credentials/gemini_keys.json` | Gemini API key and last used model | Created on first run when you paste your key |
| `_config/channels.json` | Channel settings | Copy from an existing install, or create with the [configurator](#configurator) |
| `_config/fonts/` | Fonts named in `channels.json` (Dana) | Copy from an existing install |
| `_config/templates/` | One overlay PNG per channel | Copy from an existing install |

## First run

1. **Log in to Telegram once from the terminal.** Telethon asks for your phone number, the login code Telegram sends you, and your 2FA password if you have one. Do this first with the emoji inspector, because a login prompt that appears during the GUI is hard to answer:
   ```bash
   python kernel/inspect-emoji.py
   ```
   Activate `.venv` first: `.venv\Scripts\activate` on Windows, `source .venv/bin/activate` on Linux/Termux. Enter `me` when it asks for a channel. The session is saved to `_credentials/user_session.session`.
2. **Gemini API key.** The first time the text phase runs, it asks you to paste a key from Google AI Studio. It's saved to `_credentials/gemini_keys.json`.

Alternatively, do both steps in the browser on the **Setup** page of the [web interface](#web-interface). It also asks for the Telegram API ID and hash when `_credentials/telegram_api.json` is missing.

## Web interface

A browser interface served from the same device. On Android it runs in the phone's own browser, without Termux:X11.

| Platform | Command |
|---|---|
| Windows | `run-web.bat` |
| Linux / Termux | `bash run-web.sh` |

- Starts a server at `http://127.0.0.1:8765/` and opens it in the default browser. Add `--port 9000` to use another port, or `--no-browser` to skip opening it.
- Only this device can connect. The server listens on `127.0.0.1` and refuses requests addressed to any other host name.
- Press Ctrl+C in the terminal to stop it.
- The Telegram session can be used by only one program at a time. Close `run.bat`/`run.sh`, `publisher.py` and `inspect-emoji.py` while the web interface runs, and the other way round. If the Setup page reports `database is locked`, close the other program and click **Try again**.
- If `.venv` was created before the web interface existed, the launcher installs the missing packages first.

**Pages:**
- **Telegram:** a read-only viewer.
  - **Shortcuts** lists the review channel and every channel in `channels.json`; **Chats** lists all your chats, with **Load more** for older ones.
  - Chats show their profile pictures; chats without one show coloured initials.
  - Messages show photos, albums, formatting and views. New, edited and deleted messages update live.
  - **Reactions** appear under each message with their counts; your own reaction is outlined.
    - In groups and private chats, the names of the people who reacted are shown. Reactions you haven't seen yet are in bold, and **Who reacted** loads the full list. In channels, Telegram keeps reactions anonymous, so only counts are shown.
    - Reactions update live, also on older messages.
    - A red ♥ badge in the chat list marks chats with reactions to your messages that you haven't seen yet.
  - Reading here doesn't mark messages or reactions as read. Tap a photo to open it full size.
- **Setup:** Telegram API ID and hash, Telegram login (phone, code, 2FA password), the Gemini API key, and checks for `channels.json` and Raqm.

The pipeline itself (ingestion, translation, rendering, publishing) still runs through `run.bat`/`run.sh`. Pages for it are being added to the web interface.

Images shown in the viewer (photos, profile pictures, custom emoji) are cached in `_workspace/web_cache/` and deleted after 7 days.

## Running the pipeline

| Platform | Command |
|---|---|
| Windows | `run.bat` |
| Linux / Termux | `bash run.sh` |

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

**Image:** click **Browse Local...** (PNG/JPG), or **Fetch from Telegram**:
1. Pick a chat.
2. Select a row marked `📎 MEDIA`. Text-only rows can't be selected.
3. Click **Download & Use**. The file is saved in `_workspace/`.

Click **Start Processing Pipeline** when both are set. Closing the window cancels the run.

### 2. Text phase (terminal)

1. **Model menu:** lists the Gemini models currently available. Type a number, or press Enter (or wait 5 s) to reuse the last model.
2. If the model fails or returns bad data, the menu appears again. Your text is kept. Press Ctrl+C to abort.

### 3. Graphics phase (terminal)

1. **`Define manual AOI? (y/n)`** (default `n` after 5 s):
   - `y` opens the photo surrounded by a dark grid. Click two opposite corners of the area that must stay visible. The corners can extend into the grid to add margin.
   - If the area covers more than 60% of the photo, it's fitted whole into the photo slot. Otherwise the photo is cropped around the area's center.
   - Without an area, the photo is center-cropped.
2. **`Enter background blur radius`** (default `30` after 5 s): the blur of the full-canvas background made from the same photo.
3. **Overflow menu**, shown for each channel whose headline doesn't fit its safe area (too many lines or too tall):
   - `1` shrinks the font 2 px at a time, down to 18 px. It draws at 18 px even if the text still doesn't fit.
   - `2` asks Gemini for a shorter headline, then checks again. This is the default after 5 s.
   - `3` lets you type the headline yourself.

   The shortened headline is used only for the image. The caption keeps the full headline from `<lang>.md`.

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
| `catch_all_channel` | Where previews go: `me` (Saved Messages), `@username`, or a numeric ID. Empty means no previews; the review menu still appears. |
| `chat_id` | The live channel: `@username` or a numeric ID such as `-1001234567890`. Numeric strings are converted to numbers automatically. |
| `language` | `en`, `fa`, `ar` or `ckb`. It selects `<lang>.md` and the language Gemini translates into. Channels can share a language. |
| `is_rtl` | `true` for Persian, Arabic and Kurdish. Turns on right-to-left shaping. |
| `canvas_size` | Output image size in pixels. It must equal the template's pixel size, or rendering fails. The configurator sets it from the template automatically. |
| `raw_image_placement` | Where the photo goes on the canvas: `x`, `y`, `width`, `height`. |
| `template_overlay_path` | PNG drawn over the photo, relative to the project root. Transparent areas show the photo. |
| `headline_safe_area` | The box the headline must fit in: `x_start`, `y_start`, `width`, `max_height`. The text is centered vertically inside it. |
| `font_path`, `font_size`, `font_color` | Headline font, relative to the project root. The size is the starting size before any shrinking. |
| `alignment` | `left`, `center` or `right`. Defaults to `right` for RTL and `left` otherwise. |
| `line_spacing`, `max_lines` | Line height multiplier, and the most lines allowed before the overflow menu appears. |
| `header_template`, `footer_template` | Caption HTML placed before the headline and after the body. Write `\n` for a line break. Telegram HTML tags work, including custom emoji (see [Emoji inspector](#emoji-inspector)). |

Older files may also contain `resize_mode` and `font_weight`. Nothing reads them: the photo is always cover-fitted, and the font weight comes from the font file you pick (e.g. `Dana-Bold.ttf`). The configurator drops them when you edit a channel.

## Tools

Run these with `.venv` active, from the project root.

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

Logs in to Telegram (this is also the easiest way to do the first login) and asks for a chat: `@username`, or `me` for Saved Messages. For each of the last 10 text messages it prints:
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
| `python kernel/image_engine.py` | Re-renders every channel image (overwrites `*_broadcast.jpg`) |
| `python kernel/publisher.py` | Creates any missing captions, then runs channel selection, previews and review |

`python kernel/text_engine.py` is a developer test. It sends a built-in sample text to Gemini and creates a new session folder.

## Common tasks

**Fix a translation:**
1. Edit `<lang>.md` in the session folder.
2. Run `python kernel/image_engine.py` if the headline changed.
3. Delete that language's `*_caption.txt` files so they're rebuilt from the `.md`, or edit them directly.
4. Run `python kernel/publisher.py`.

**Change one caption only:** edit `<channel>_caption.txt`, then press `R` in the review menu.

**Fix a headline that renders badly:** edit the first line of `<lang>.md`, then re-render with `python kernel/image_engine.py`.

**Test without posting live:** keep `catch_all_channel` set to `me` and answer `S` at the review menu.

## Project layout

```
kernel/
  main.py           Orchestrator and ingestion window
  text_engine.py    Gemini translation -> <lang>.md
  image_engine.py   Image rendering and headline layout
  publisher.py      Captions, previews, review, live posting
  auth_manager.py   Telegram client from _credentials/
  common.py         Shared paths, config loading, Gemini helpers
  configurator.py   Channel settings editor
  inspect-emoji.py  Message/emoji inspector
  webapp.py         Web interface server (FastAPI)
  telegram_service.py  Telegram login, viewer data and live updates for the web interface
  web/              Web interface page (HTML, CSS, JavaScript)
  lib/              FriBiDi for Windows (see lib/README.txt)
requirements.txt    Python packages
setup.*, run.*      Setup and launch scripts per platform
run-web.*           Web interface launchers
```
