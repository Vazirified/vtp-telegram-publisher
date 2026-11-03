import sys
# Prevent the creation of __pycache__ folders
sys.dont_write_bytecode = True

import os
import shutil
import asyncio
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# --- Import Core Engines ---
try:
    import auth_manager
    import text_engine
    import image_engine
    import publisher
except ImportError as e:
    print(f"[FATAL] Core module missing: {e}")
    print("Please ensure auth_manager.py, text_engine.py, image_engine.py, publisher.py, and telethon are available.")
    sys.exit(1)

from common import WORKSPACE_DIR

# --- GLOBAL UI COLOR & FONT CONFIGURATION (DARK MODE) ---
BG_MAIN = "#1e1e1e"        # Main window background
BG_SEC = "#2d2d2d"         # Inputs and list backgrounds
FG_MAIN = "#e0e0e0"        # Main text color
FG_MUTED = "#888888"       # Disabled/Muted text
BTN_GRAY = "#424242"       # Default button
BTN_GREEN = "#2e7d32"      # Action button
BTN_BLUE = "#1565c0"       # Secondary action button
ACCENT_BLUE = "#64b5f6"    # Hyperlink/Path colors

FONT_MAIN = ("Segoe UI", 11)
FONT_BOLD = ("Segoe UI", 11, "bold")
FONT_SMALL = ("Segoe UI", 10)
FONT_SMALL_BOLD = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI", 12, "bold")

# Button style name -> (background, background while pressed)
BUTTON_COLORS = {
    "gray": (BTN_GRAY, "#555555"),
    "green": (BTN_GREEN, "#388e3c"),
    "blue": (BTN_BLUE, "#1976d2"),
}

def make_button(parent, text, command=None, kind="gray", font=FONT_SMALL, **kwargs):
    """Creates a flat dark-mode button in one of the BUTTON_COLORS styles."""
    bg, active_bg = BUTTON_COLORS[kind]
    return tk.Button(parent, text=text, command=command, bg=bg, fg=FG_MAIN,
                     activebackground=active_bg, activeforeground="white",
                     font=font, relief="flat", **kwargs)

def make_preview(text, limit=90):
    """Flattens a message onto one line and cuts it to `limit` characters with an ellipsis."""
    preview = text.replace('\n', ' ')
    if len(preview) > limit:
        preview = preview[:limit - 3] + "..."
    return preview

# ==========================================
# TELEGRAM BACKGROUND TASKS
# ==========================================
def run_telegram_task(task, callback, error_callback):
    """Runs `await task(client)` with a fresh Telegram client on a background thread.

    The task's return value is passed to callback. A missing client or any exception
    is passed to error_callback as a message string.
    """
    def run_async():
        async def run():
            client = auth_manager.get_client()
            if not client:
                raise RuntimeError("Could not initialize the Telegram client. Check _credentials/telegram_api.json.")
            try:
                await client.start()
                return await task(client)
            finally:
                await client.disconnect()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(run())
        except Exception as e:
            error_callback(str(e))
        else:
            callback(result)
        finally:
            loop.close()

    threading.Thread(target=run_async, daemon=True).start()

def fetch_telegram_dialogs_async(callback, error_callback, offset_date=None):
    """Fetches the 30 most recent chats/dialogs, supporting pagination via offset_date."""
    async def fetch(client):
        kwargs = {'limit': 30}
        if offset_date: kwargs['offset_date'] = offset_date

        dialogs_data = []
        async for dialog in client.iter_dialogs(**kwargs):
            name = dialog.name or "Unknown Chat"
            dialogs_data.append({"id": dialog.id, "name": name, "date": dialog.date})
        return dialogs_data

    run_telegram_task(fetch, callback, error_callback)

def fetch_telegram_messages_async(target_entity_id, callback, error_callback, offset_id=0):
    """Fetches the last 20 text messages for the Text Ingestion UI."""
    async def fetch(client):
        entity = await client.get_entity(target_entity_id)
        kwargs = {'limit': 20}
        if offset_id: kwargs['offset_id'] = offset_id

        messages = []
        async for msg in client.iter_messages(entity, **kwargs):
            if msg.text:
                date_str = msg.date.strftime("%Y-%m-%d %H:%M")
                messages.append({"id": msg.id, "text": msg.text, "date": date_str})
        return messages

    run_telegram_task(fetch, callback, error_callback)

def fetch_telegram_media_context_async(target_entity_id, callback, error_callback, offset_id=0):
    """Fetches all messages (text and media) to provide conversation context for finding files."""
    async def fetch(client):
        entity = await client.get_entity(target_entity_id)
        kwargs = {'limit': 20}
        if offset_id: kwargs['offset_id'] = offset_id

        context_msgs = []
        async for msg in client.iter_messages(entity, **kwargs):
            has_media = bool(msg.photo or msg.document)

            if msg.text or has_media:
                date_str = msg.date.strftime("%m-%d %H:%M")
                text_snippet = (msg.text or "").replace('\n', ' ')

                if not text_snippet and has_media:
                    text_snippet = "[No Caption]"

                context_msgs.append({
                    "id": msg.id,
                    "text": text_snippet,
                    "date": date_str,
                    "has_media": has_media
                })
        return context_msgs

    run_telegram_task(fetch, callback, error_callback)

def download_telegram_media_async(target_entity_id, message_id, callback, error_callback):
    """Downloads a specific photo or document message to the workspace folder."""
    async def download(client):
        entity = await client.get_entity(target_entity_id)
        msg = await client.get_messages(entity, ids=message_id)

        if not (msg and (msg.photo or msg.document)):
            raise RuntimeError("Selected message does not contain a downloadable file.")

        os.makedirs(WORKSPACE_DIR, exist_ok=True)
        downloaded_file = await client.download_media(msg, file=WORKSPACE_DIR)
        if not downloaded_file or not os.path.exists(downloaded_file):
            raise RuntimeError("Could not download file (unsupported media type or expired).")
        return downloaded_file

    run_telegram_task(download, callback, error_callback)

# ==========================================
# PAGED TELEGRAM BROWSER WINDOW
# ==========================================
class PagedBrowser:
    """A window listing Telegram items page by page, with an action button and "Load More".

    The window opens once the first page arrives. Items are kept in self.items by row id.
    - columns: list of (column_id, heading, width, anchor); a width of None lets the column stretch.
    - fetch(cursor, on_success, on_error) loads one page; next_cursor(item) gives the cursor
      after the last item of a page.
    - on_action(browser) runs for the action button.
    - add_extras(browser) adds widgets above the list; setup_tree(browser) adds list bindings.
    - empty_notice is (messagebox function, title, message) shown when the first page is empty;
      error_notice is (title, message prefix) for fetch errors.
    """
    def __init__(self, root, geometry, trigger_btn, busy_text, title, header_text, columns,
                 selectmode, fetch, row_values, next_cursor, action_text, on_action,
                 empty_notice, no_more_text, error_notice,
                 row_tags=None, add_extras=None, setup_tree=None, header_pady=(10, 5)):
        self.root = root
        self.geometry = geometry
        self.trigger_btn = trigger_btn
        self.title = title
        self.header_text = header_text
        self.header_pady = header_pady
        self.columns = columns
        self.selectmode = selectmode
        self.fetch = fetch
        self.row_values = row_values
        self.row_tags = row_tags
        self.next_cursor = next_cursor
        self.action_text = action_text
        self.on_action = on_action
        self.add_extras = add_extras
        self.setup_tree = setup_tree
        self.empty_notice = empty_notice
        self.no_more_text = no_more_text
        self.error_notice = error_notice

        self.cursor = None
        self.items = {}
        self.win = self.tree = self.action_btn = self.load_btn = None

        trigger_btn.config(text=busy_text, state="disabled")
        self.load()

    def load(self):
        if self.load_btn: self.load_btn.config(text="Loading...", state="disabled")
        self.fetch(self.cursor, self.on_success, self.on_error)

    def restore_trigger(self):
        self.trigger_btn.config(text=self.trigger_btn._original_text, state="normal")

    def build_window(self):
        self.win = tk.Toplevel(self.root)
        self.win.title(self.title)
        self.win.geometry(self.geometry)
        self.win.configure(bg=BG_MAIN)
        tk.Label(self.win, text=self.header_text, font=FONT_SMALL_BOLD, bg=BG_MAIN, fg=FG_MAIN).pack(anchor="w", pady=self.header_pady, padx=10)

        if self.add_extras: self.add_extras(self)

        list_frame = tk.Frame(self.win, bg=BG_MAIN)
        list_frame.pack(fill="both", expand=True, padx=10, pady=5)
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")

        column_ids = [col[0] for col in self.columns]
        self.tree = ttk.Treeview(list_frame, columns=column_ids, show="headings", selectmode=self.selectmode, yscrollcommand=scrollbar.set)
        for column_id, heading, width, anchor in self.columns:
            self.tree.heading(column_id, text=heading)
            if width:
                self.tree.column(column_id, width=width, anchor=anchor, stretch=False)
            else:
                self.tree.column(column_id, anchor=anchor)

        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.tree.yview)

        if self.setup_tree: self.setup_tree(self)

        btn_frame = tk.Frame(self.win, bg=BG_MAIN)
        btn_frame.pack(fill="x", padx=10, pady=10)
        self.action_btn = make_button(btn_frame, self.action_text, lambda: self.on_action(self), kind="green", font=FONT_SMALL_BOLD, pady=4)
        self.action_btn.pack(side="left", expand=True, fill="x", padx=(0, 5))
        self.load_btn = make_button(btn_frame, "Load More", self.load, kind="blue", font=FONT_SMALL_BOLD, pady=4)
        self.load_btn.pack(side="right", expand=True, fill="x", padx=(5, 0))

    def on_success(self, new_items):
        self.restore_trigger()

        if not self.win:
            if not new_items:
                show, title, message = self.empty_notice
                show(title, message)
                return
            self.build_window()

        if not new_items:
            self.load_btn.config(text=self.no_more_text, state="disabled")
            return

        for item in new_items:
            iid = str(item['id'])
            self.items[iid] = item
            tags = self.row_tags(item) if self.row_tags else ()
            self.tree.insert("", tk.END, iid=iid, values=self.row_values(item), tags=tags)

        self.cursor = self.next_cursor(new_items[-1])
        self.load_btn.config(text="Load More", state="normal")

    def on_error(self, err_msg):
        self.restore_trigger()
        if self.load_btn: self.load_btn.config(text="Load More", state="normal")
        title, prefix = self.error_notice
        messagebox.showerror(title, f"{prefix}:\n\n{err_msg}")


def run_ingestion_gui():
    root = tk.Tk()
    root.title("EPLANET Pipeline: Data Ingestion")

    # --- DYNAMIC SCREEN QUADRANT LOGIC ---
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    quad_w = screen_w // 2
    quad_h = screen_h // 2

    # Format: "width x height + x_offset + y_offset"
    quadrant_geometry = f"{quad_w}x{quad_h}+0+0"
    root.geometry(quadrant_geometry)

    root.configure(padx=20, pady=20, bg=BG_MAIN)

    # Configure ttk styles for the Treeview tables in Dark Mode
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("Treeview",
                    background=BG_SEC,
                    fieldbackground=BG_SEC,
                    foreground=FG_MAIN,
                    font=FONT_MAIN,
                    rowheight=28,
                    borderwidth=0)
    style.configure("Treeview.Heading",
                    background=BG_MAIN,
                    foreground=FG_MAIN,
                    font=FONT_SMALL_BOLD,
                    borderwidth=1)
    style.map("Treeview", background=[('selected', '#4a4a4a')])
    style.map("Treeview.Heading", background=[('active', '#3a3a3a')])

    payload = {"text": None, "image_path": None}

    # ==========================================
    # 1. CHAT / DIALOG BROWSER
    # ==========================================
    def create_dialog_browser(title, next_step_callback, trigger_btn):
        def on_select(browser):
            selected_items = browser.tree.selection()
            if not selected_items: return

            selected_dialog = browser.items.get(selected_items[0])
            if selected_dialog:
                browser.win.destroy()
                next_step_callback(selected_dialog['id'], selected_dialog['name'])

        PagedBrowser(
            root, quadrant_geometry, trigger_btn, busy_text="Fetching Chats...",
            title=title, header_text="Recent Telegram Chats:",
            columns=[("Chat Name", "Chat Name", None, "w")],
            selectmode="browse",
            fetch=lambda cursor, ok, err: fetch_telegram_dialogs_async(ok, err, offset_date=cursor),
            row_values=lambda d: (d['name'],),
            next_cursor=lambda d: d['date'],
            action_text="View Contents", on_action=on_select,
            setup_tree=lambda browser: browser.tree.bind("<Double-Button-1>", lambda event: on_select(browser)),
            empty_notice=(messagebox.showerror, "Error", "Could not find any recent chats."),
            no_more_text="No more chats",
            error_notice=("Telegram Error", "Failed to fetch chats"),
        )


    # ==========================================
    # 2. TEXT INGESTION SECTION
    # ==========================================
    text_header_frame = tk.Frame(root, bg=BG_MAIN)
    text_header_frame.pack(fill="x", pady=(0, 5))
    tk.Label(text_header_frame, text="1. Source Text (Paste manually or Fetch):", font=FONT_BOLD, bg=BG_MAIN, fg=FG_MAIN).pack(side="left")

    fetch_txt_btn = make_button(text_header_frame, "Fetch Text from Telegram", width=22)
    fetch_txt_btn._original_text = "Fetch Text from Telegram"
    fetch_txt_btn.pack(side="right")

    text_input = tk.Text(root, height=15, width=80, font=FONT_MAIN, wrap="word", bg=BG_SEC, fg=FG_MAIN, insertbackground=FG_MAIN, relief="flat")
    text_input.pack(pady=5, fill="both", expand=True)

    def open_message_browser(dialog_id, dialog_name):
        def add_multi_select_toggle(browser):
            browser.multi_select_var = tk.BooleanVar(value=True)
            tk.Checkbutton(browser.win, text="Easy Multi-Select (Click to toggle, no Ctrl needed)", variable=browser.multi_select_var, font=FONT_SMALL, bg=BG_MAIN, fg=FG_MAIN, selectcolor=BG_SEC, activebackground=BG_MAIN, activeforeground=FG_MAIN).pack(anchor="w", padx=10, pady=(0, 5))

        def bind_click_toggle(browser):
            tree = browser.tree

            def on_tree_click(event):
                if browser.multi_select_var.get():
                    region = tree.identify("region", event.x, event.y)
                    if region in ("cell", "tree", "indicator"):
                        item_id = tree.identify_row(event.y)
                        if item_id:
                            if item_id in tree.selection():
                                tree.selection_remove(item_id)
                            else:
                                tree.selection_add(item_id)
                            tree.focus(item_id)
                            return "break"

            tree.bind("<Button-1>", on_tree_click)

        def on_insert(browser):
            selected_items = browser.tree.selection()
            if not selected_items: return
            for item_id in selected_items:
                msg_data = browser.items.get(item_id)
                if msg_data:
                    text_input.insert(tk.END, msg_data['text'] + "\n\n")
            browser.win.destroy()

        PagedBrowser(
            root, quadrant_geometry, fetch_txt_btn, busy_text="Fetching...",
            title=f"Texts from: {dialog_name}", header_text="Select messages:", header_pady=(10, 0),
            columns=[("Date", "Timestamp", 140, "center"), ("Message Text", "Message Text", None, "e")],
            selectmode="extended",
            fetch=lambda cursor, ok, err: fetch_telegram_messages_async(dialog_id, ok, err, offset_id=cursor),
            row_values=lambda msg: (msg['date'], make_preview(msg['text'])),
            next_cursor=lambda msg: msg['id'],
            action_text="Insert Selected", on_action=on_insert,
            add_extras=add_multi_select_toggle, setup_tree=bind_click_toggle,
            empty_notice=(messagebox.showinfo, "Telegram", f"No text messages found in {dialog_name}."),
            no_more_text="No more messages",
            error_notice=("Error", "Failed to fetch"),
        )

    fetch_txt_btn.config(command=lambda: create_dialog_browser("Select Chat for Text", open_message_browser, fetch_txt_btn))


    # ==========================================
    # 3. IMAGE / MEDIA INGESTION SECTION
    # ==========================================
    tk.Label(root, text="\n2. Select Raw Image / File:", font=FONT_BOLD, bg=BG_MAIN, fg=FG_MAIN).pack(anchor="w")

    img_frame = tk.Frame(root, bg=BG_MAIN)
    img_frame.pack(fill="x", pady=5)

    img_path_var = tk.StringVar()
    img_label = tk.Label(img_frame, textvariable=img_path_var, font=FONT_SMALL, fg=ACCENT_BLUE, bg=BG_SEC, anchor="w", padx=5)
    img_label.pack(side="left", fill="x", expand=True, padx=(0, 10), ipady=3)

    action_btn_frame = tk.Frame(img_frame, bg=BG_MAIN)
    action_btn_frame.pack(side="right")

    def browse_image():
        filepath = filedialog.askopenfilename(title="Select Raw Image", filetypes=[("Image Files", "*.png;*.jpg;*.jpeg")])
        if filepath: img_path_var.set(filepath)

    make_button(action_btn_frame, "Browse Local...", browse_image, width=15).pack(side="left", padx=(0, 10))

    fetch_img_btn = make_button(action_btn_frame, "Fetch from Telegram", width=22)
    fetch_img_btn._original_text = "Fetch from Telegram"
    fetch_img_btn.pack(side="left")

    def open_media_context_browser(dialog_id, dialog_name):
        def setup_media_tree(browser):
            tree = browser.tree
            tree.tag_configure("disabled", foreground=FG_MUTED)

            def on_select_check(event):
                selected_items = tree.selection()
                if not selected_items: return
                if "disabled" in tree.item(selected_items[0], "tags"):
                    tree.selection_remove(selected_items[0])

            tree.bind("<<TreeviewSelect>>", on_select_check)

        def on_download(browser):
            selected_items = browser.tree.selection()
            if not selected_items: return

            target_msg = browser.items.get(selected_items[0])
            if not target_msg or not target_msg['has_media']:
                messagebox.showwarning("Invalid Selection", "This message does not contain a file or photo.\nPlease select a message marked with 📎 MEDIA.")
                return

            browser.action_btn.config(text="Downloading...", state="disabled")
            browser.load_btn.config(state="disabled")

            def on_dl_success(filepath):
                img_path_var.set(filepath)
                browser.win.destroy()

            def on_dl_error(err_msg):
                browser.action_btn.config(text="Download & Use", state="normal")
                browser.load_btn.config(state="normal")
                messagebox.showerror("Error", f"Failed to download file:\n\n{err_msg}")

            download_telegram_media_async(dialog_id, target_msg['id'], on_dl_success, on_dl_error)

        PagedBrowser(
            root, quadrant_geometry, fetch_img_btn, busy_text="Fetching Messages...",
            title=f"Media & Context from: {dialog_name}", header_text="Select a message containing a file/photo to download:",
            columns=[("Date", "Timestamp", 140, "center"), ("Type", "Type", 100, "center"), ("Message Text", "Message Text", None, "e")],
            selectmode="browse",
            fetch=lambda cursor, ok, err: fetch_telegram_media_context_async(dialog_id, ok, err, offset_id=cursor),
            row_values=lambda msg: (msg['date'], "📎 MEDIA" if msg['has_media'] else "💬 TEXT", make_preview(msg['text'])),
            row_tags=lambda msg: () if msg['has_media'] else ("disabled",),
            next_cursor=lambda msg: msg['id'],
            action_text="Download & Use", on_action=on_download,
            setup_tree=setup_media_tree,
            empty_notice=(messagebox.showinfo, "Telegram", f"No messages found in {dialog_name}."),
            no_more_text="No more messages",
            error_notice=("Error", "Failed to fetch context"),
        )

    fetch_img_btn.config(command=lambda: create_dialog_browser("Select Chat for Image", open_media_context_browser, fetch_img_btn))


    # ==========================================
    # 4. SUBMISSION HANDLER
    # ==========================================
    submit_frame = tk.Frame(root, bg=BG_MAIN)
    submit_frame.pack(fill="x", pady=(20, 0))

    def on_submit():
        raw_text = text_input.get("1.0", tk.END).strip()
        img_path = img_path_var.get().strip()

        if not raw_text:
            messagebox.showerror("Missing Data", "Please paste or fetch the source text.")
            return
        if not img_path or not os.path.exists(img_path):
            messagebox.showerror("Missing Data", "Please select a valid raw image file.")
            return

        payload["text"] = raw_text
        payload["image_path"] = img_path
        root.quit()
        root.destroy()

    make_button(submit_frame, "Start Processing Pipeline", on_submit, kind="green", font=FONT_TITLE, width=30, pady=8).pack(side="right")

    def on_close():
        root.quit()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()

    return payload.get("text"), payload.get("image_path")

def main():
    print("========================================================")
    print("  EPLANET MASTER ORCHESTRATOR")
    print("========================================================")

    print("\n[~] Launching Data Ingestion Gateway...")
    raw_text, raw_image_path = run_ingestion_gui()

    if not raw_text or not raw_image_path:
        print("[!] Ingestion cancelled or missing data. Aborting pipeline.")
        return

    print("\n========================================================")
    print("  PHASE 2: TEXT PROCESSING")
    print("========================================================")
    session_dir = text_engine.execute_text_pipeline(raw_text)

    if not session_dir or not os.path.exists(session_dir):
        print("[ERROR] Text pipeline failed to generate a session directory. Aborting.")
        return

    print("\n[~] Staging Raw Image Asset...")
    _, ext = os.path.splitext(raw_image_path)
    staged_image_path = os.path.join(session_dir, f"raw_image{ext.lower()}")
    shutil.copy2(raw_image_path, staged_image_path)
    print(f"  [+] Image secured at: {staged_image_path}")

    print("\n========================================================")
    print("  PHASE 3: GRAPHICS RENDERING")
    print("========================================================")
    image_engine.render_channel_assets(session_dir)

    print("\n========================================================")
    print("  PHASE 4: DEPLOYMENT")
    print("========================================================")
    try:
        asyncio.run(publisher.main())
    except KeyboardInterrupt:
        print("\n[!] Publisher terminated by user.")

    print("\n========================================================")
    print("  PIPELINE EXECUTION FINISHED")
    print("========================================================")

if __name__ == "__main__":
    main()
