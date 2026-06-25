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

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE_DIR = os.path.join(PROJECT_ROOT, "_workspace")

def fetch_telegram_dialogs_async(callback, error_callback, offset_date=None):
    """Fetches the 30 most recent chats/dialogs, supporting pagination via offset_date."""
    def run_async():
        async def fetch():
            client = auth_manager.get_client()
            if not client: return None
            dialogs_data = []
            try:
                await client.start()
                kwargs = {'limit': 30}
                if offset_date: kwargs['offset_date'] = offset_date

                async for dialog in client.iter_dialogs(**kwargs):
                    name = dialog.name or "Unknown Chat"
                    dialogs_data.append({"id": dialog.id, "name": name, "date": dialog.date})
                return dialogs_data
            except Exception as e:
                return str(e)
            finally:
                await client.disconnect()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(fetch())
        loop.close()

        if isinstance(result, str):
            error_callback(result)
        else:
            callback(result)

    threading.Thread(target=run_async, daemon=True).start()

def fetch_telegram_messages_async(target_entity_id, callback, error_callback, offset_id=0):
    """Fetches the last 20 text messages for the Text Ingestion UI."""
    def run_async():
        async def fetch():
            client = auth_manager.get_client()
            if not client: return None
            messages = []
            try:
                await client.start()
                entity = await client.get_entity(target_entity_id)
                kwargs = {'limit': 20}
                if offset_id: kwargs['offset_id'] = offset_id

                async for msg in client.iter_messages(entity, **kwargs):
                    if msg.text:
                        date_str = msg.date.strftime("%Y-%m-%d %H:%M")
                        messages.append({"id": msg.id, "text": msg.text, "date": date_str})
                return messages
            except Exception as e:
                return str(e)
            finally:
                await client.disconnect()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(fetch())
        loop.close()

        if isinstance(result, str): error_callback(result)
        else: callback(result)

    threading.Thread(target=run_async, daemon=True).start()

def fetch_telegram_media_context_async(target_entity_id, callback, error_callback, offset_id=0):
    """Fetches all messages (text and media) to provide conversation context for finding files."""
    def run_async():
        async def fetch():
            client = auth_manager.get_client()
            if not client: return None
            context_msgs = []
            try:
                await client.start()
                entity = await client.get_entity(target_entity_id)
                kwargs = {'limit': 20}
                if offset_id: kwargs['offset_id'] = offset_id

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
            except Exception as e:
                return str(e)
            finally:
                await client.disconnect()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(fetch())
        loop.close()

        if isinstance(result, str): error_callback(result)
        else: callback(result)

    threading.Thread(target=run_async, daemon=True).start()

def download_telegram_media_async(target_entity_id, message_id, callback, error_callback):
    """Downloads a specific photo or document message to the workspace folder."""
    def run_async():
        async def download():
            client = auth_manager.get_client()
            if not client: return None
            try:
                await client.start()
                entity = await client.get_entity(target_entity_id)
                msg = await client.get_messages(entity, ids=message_id)

                if msg and (msg.photo or msg.document):
                    os.makedirs(WORKSPACE_DIR, exist_ok=True)
                    downloaded_file = await client.download_media(msg, file=WORKSPACE_DIR)
                    if downloaded_file:
                        return downloaded_file
                    else:
                        return "Could not download file (unsupported media type or expired)."
                return "Selected message does not contain a downloadable file."
            except Exception as e:
                return str(e)
            finally:
                await client.disconnect()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(download())
        loop.close()

        if isinstance(result, str) and os.path.exists(result):
            callback(result)
        else:
            error_callback(str(result))

    threading.Thread(target=run_async, daemon=True).start()


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
    # 1. CHAT / DIALOG BROWSER (TREEVIEW)
    # ==========================================
    def create_dialog_browser(title, next_step_callback, trigger_btn):
        trigger_btn.config(text="Fetching Chats...", state="disabled")
        all_dialogs = []
        state = {'last_date': None, 'win': None, 'listbox': None, 'load_btn': None}

        columns = ("Chat Name",)

        def load_dialogs():
            if state['load_btn']: state['load_btn'].config(text="Loading...", state="disabled")
            fetch_telegram_dialogs_async(on_dlg_success, on_dlg_error, offset_date=state['last_date'])

        def on_dlg_success(new_dialogs):
            trigger_btn.config(text=trigger_btn._original_text, state="normal")

            if not state['win']:
                if not new_dialogs:
                    messagebox.showerror("Error", "Could not find any recent chats.")
                    return

                state['win'] = tk.Toplevel(root)
                state['win'].title(title)
                # Apply dynamic quadrant geometry
                state['win'].geometry(quadrant_geometry)
                state['win'].configure(bg=BG_MAIN)

                tk.Label(state['win'], text="Recent Telegram Chats:", font=FONT_SMALL_BOLD, bg=BG_MAIN, fg=FG_MAIN).pack(anchor="w", pady=(10, 5), padx=10)

                list_frame = tk.Frame(state['win'], bg=BG_MAIN)
                list_frame.pack(fill="both", expand=True, padx=10, pady=5)
                scrollbar = tk.Scrollbar(list_frame)
                scrollbar.pack(side="right", fill="y")

                state['listbox'] = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="browse", yscrollcommand=scrollbar.set)
                state['listbox'].heading("Chat Name", text="Chat Name")
                state['listbox'].column("Chat Name", anchor="w")

                state['listbox'].pack(side="left", fill="both", expand=True)
                scrollbar.config(command=state['listbox'].yview)

                def on_select(event=None):
                    selected_items = state['listbox'].selection()
                    if not selected_items: return

                    selected_dialog_id = selected_items[0]
                    selected_dialog = next((d for d in all_dialogs if str(d['id']) == selected_dialog_id), None)
                    if selected_dialog:
                        state['win'].destroy()
                        next_step_callback(selected_dialog['id'], selected_dialog['name'])

                state['listbox'].bind("<Double-Button-1>", on_select)

                btn_frame = tk.Frame(state['win'], bg=BG_MAIN)
                btn_frame.pack(fill="x", padx=10, pady=10)
                tk.Button(btn_frame, text="View Contents", command=on_select, bg=BTN_GREEN, fg=FG_MAIN, activebackground="#388e3c", activeforeground="white", font=FONT_SMALL_BOLD, relief="flat", pady=4).pack(side="left", expand=True, fill="x", padx=(0, 5))
                state['load_btn'] = tk.Button(btn_frame, text="Load More", command=load_dialogs, bg=BTN_BLUE, fg=FG_MAIN, activebackground="#1976d2", activeforeground="white", font=FONT_SMALL_BOLD, relief="flat", pady=4)
                state['load_btn'].pack(side="right", expand=True, fill="x", padx=(5, 0))

            if not new_dialogs:
                if state['load_btn']: state['load_btn'].config(text="No more chats", state="disabled")
                return

            for d in new_dialogs:
                all_dialogs.append(d)
                state['listbox'].insert("", tk.END, iid=str(d['id']), values=(d['name'],))

            state['last_date'] = new_dialogs[-1]['date']
            if state['load_btn']: state['load_btn'].config(text="Load More", state="normal")

        def on_dlg_error(err_msg):
            trigger_btn.config(text=trigger_btn._original_text, state="normal")
            if state['load_btn']: state['load_btn'].config(text="Load More", state="normal")
            messagebox.showerror("Telegram Error", f"Failed to fetch chats:\n\n{err_msg}")

        load_dialogs()


    # ==========================================
    # 2. TEXT INGESTION SECTION
    # ==========================================
    text_header_frame = tk.Frame(root, bg=BG_MAIN)
    text_header_frame.pack(fill="x", pady=(0, 5))
    tk.Label(text_header_frame, text="1. Source Text (Paste manually or Fetch):", font=FONT_BOLD, bg=BG_MAIN, fg=FG_MAIN).pack(side="left")

    fetch_txt_btn = tk.Button(text_header_frame, text="Fetch Text from Telegram", font=FONT_SMALL, bg=BTN_GRAY, fg=FG_MAIN, activebackground="#555555", activeforeground="white", relief="flat", width=22)
    fetch_txt_btn._original_text = "Fetch Text from Telegram"
    fetch_txt_btn.pack(side="right")

    text_input = tk.Text(root, height=15, width=80, font=FONT_MAIN, wrap="word", bg=BG_SEC, fg=FG_MAIN, insertbackground=FG_MAIN, relief="flat")
    text_input.pack(pady=5, fill="both", expand=True)

    def open_message_browser(dialog_id, dialog_name):
        fetch_txt_btn.config(text="Fetching...", state="disabled")
        all_messages = []
        state = {'last_id': 0, 'win': None, 'listbox': None, 'load_btn': None, 'multi_select_var': None}

        text_cols = ("Date", "Message Text")

        def load_msgs():
            if state['load_btn']: state['load_btn'].config(text="Loading...", state="disabled")
            fetch_telegram_messages_async(dialog_id, on_success, on_error, offset_id=state['last_id'])

        def on_success(new_msgs):
            fetch_txt_btn.config(text=fetch_txt_btn._original_text, state="normal")
            if not state['win']:
                if not new_msgs:
                    messagebox.showinfo("Telegram", f"No text messages found in {dialog_name}.")
                    return
                state['win'] = tk.Toplevel(root)
                state['win'].title(f"Texts from: {dialog_name}")
                # Apply dynamic quadrant geometry
                state['win'].geometry(quadrant_geometry)
                state['win'].configure(bg=BG_MAIN)
                tk.Label(state['win'], text="Select messages:", font=FONT_SMALL_BOLD, bg=BG_MAIN, fg=FG_MAIN).pack(anchor="w", pady=(10, 0), padx=10)

                state['multi_select_var'] = tk.BooleanVar(value=True)
                tk.Checkbutton(state['win'], text="Easy Multi-Select (Click to toggle, no Ctrl needed)", variable=state['multi_select_var'], font=FONT_SMALL, bg=BG_MAIN, fg=FG_MAIN, selectcolor=BG_SEC, activebackground=BG_MAIN, activeforeground=FG_MAIN).pack(anchor="w", padx=10, pady=(0, 5))

                list_frame = tk.Frame(state['win'], bg=BG_MAIN)
                list_frame.pack(fill="both", expand=True, padx=10, pady=5)
                scrollbar = tk.Scrollbar(list_frame)
                scrollbar.pack(side="right", fill="y")

                state['listbox'] = ttk.Treeview(list_frame, columns=text_cols, show="headings", selectmode="extended", yscrollcommand=scrollbar.set)

                state['listbox'].heading("Date", text="Timestamp")
                state['listbox'].column("Date", width=140, anchor="center", stretch=False)

                state['listbox'].heading("Message Text", text="Message Text")
                state['listbox'].column("Message Text", anchor="e")

                state['listbox'].pack(side="left", fill="both", expand=True)
                scrollbar.config(command=state['listbox'].yview)

                def on_tree_click(event):
                    if state['multi_select_var'].get():
                        region = state['listbox'].identify("region", event.x, event.y)
                        if region in ("cell", "tree", "indicator"):
                            item_id = state['listbox'].identify_row(event.y)
                            if item_id:
                                if item_id in state['listbox'].selection():
                                    state['listbox'].selection_remove(item_id)
                                else:
                                    state['listbox'].selection_add(item_id)
                                state['listbox'].focus(item_id)
                                return "break"

                state['listbox'].bind("<Button-1>", on_tree_click)

                def on_insert():
                    selected_items = state['listbox'].selection()
                    if not selected_items: return
                    for item_id in selected_items:
                        msg_data = next((m for m in all_messages if str(m['id']) == item_id), None)
                        if msg_data:
                            text_input.insert(tk.END, msg_data['text'] + "\n\n")
                    state['win'].destroy()

                btn_frame = tk.Frame(state['win'], bg=BG_MAIN)
                btn_frame.pack(fill="x", padx=10, pady=10)
                tk.Button(btn_frame, text="Insert Selected", command=on_insert, bg=BTN_GREEN, fg=FG_MAIN, activebackground="#388e3c", activeforeground="white", font=FONT_SMALL_BOLD, relief="flat", pady=4).pack(side="left", expand=True, fill="x", padx=(0, 5))
                state['load_btn'] = tk.Button(btn_frame, text="Load More", command=load_msgs, bg=BTN_BLUE, fg=FG_MAIN, activebackground="#1976d2", activeforeground="white", font=FONT_SMALL_BOLD, relief="flat", pady=4)
                state['load_btn'].pack(side="right", expand=True, fill="x", padx=(5, 0))

            if not new_msgs:
                if state['load_btn']: state['load_btn'].config(text="No more messages", state="disabled")
                return

            for msg in new_msgs:
                all_messages.append(msg)
                preview = msg['text'].replace('\n', ' ')
                # CUTTING STRATEGY: Limit length to 90 chars and append an ellipsis
                if len(preview) > 90:
                    preview = preview[:87] + "..."
                state['listbox'].insert("", tk.END, iid=str(msg['id']), values=(msg['date'], preview))

            state['last_id'] = new_msgs[-1]['id']
            if state['load_btn']: state['load_btn'].config(text="Load More", state="normal")

        def on_error(err_msg):
            fetch_txt_btn.config(text=fetch_txt_btn._original_text, state="normal")
            if state['load_btn']: state['load_btn'].config(text="Load More", state="normal")
            messagebox.showerror("Error", f"Failed to fetch:\n\n{err_msg}")

        load_msgs()

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

    tk.Button(action_btn_frame, text="Browse Local...", font=FONT_SMALL, command=browse_image, bg=BTN_GRAY, fg=FG_MAIN, activebackground="#555555", activeforeground="white", relief="flat", width=15).pack(side="left", padx=(0, 10))

    fetch_img_btn = tk.Button(action_btn_frame, text="Fetch from Telegram", font=FONT_SMALL, bg=BTN_GRAY, fg=FG_MAIN, activebackground="#555555", activeforeground="white", relief="flat", width=22)
    fetch_img_btn._original_text = "Fetch from Telegram"
    fetch_img_btn.pack(side="left")

    def open_media_context_browser(dialog_id, dialog_name):
        fetch_img_btn.config(text="Fetching Messages...", state="disabled")
        all_msgs = []
        state = {'last_id': 0, 'win': None, 'listbox': None, 'load_btn': None, 'dl_btn': None}

        media_cols = ("Date", "Type", "Message Text")

        def load_context():
            if state['load_btn']: state['load_btn'].config(text="Loading...", state="disabled")
            fetch_telegram_media_context_async(dialog_id, on_success, on_error, offset_id=state['last_id'])

        def on_success(new_msgs):
            fetch_img_btn.config(text=fetch_img_btn._original_text, state="normal")
            if not state['win']:
                if not new_msgs:
                    messagebox.showinfo("Telegram", f"No messages found in {dialog_name}.")
                    return
                state['win'] = tk.Toplevel(root)
                state['win'].title(f"Media & Context from: {dialog_name}")
                # Apply dynamic quadrant geometry
                state['win'].geometry(quadrant_geometry)
                state['win'].configure(bg=BG_MAIN)
                tk.Label(state['win'], text="Select a message containing a file/photo to download:", font=FONT_SMALL_BOLD, bg=BG_MAIN, fg=FG_MAIN).pack(anchor="w", pady=(10, 5), padx=10)

                list_frame = tk.Frame(state['win'], bg=BG_MAIN)
                list_frame.pack(fill="both", expand=True, padx=10, pady=5)
                scrollbar = tk.Scrollbar(list_frame)
                scrollbar.pack(side="right", fill="y")

                state['listbox'] = ttk.Treeview(list_frame, selectmode="browse", columns=media_cols, show="headings", yscrollcommand=scrollbar.set)

                state['listbox'].heading("Date", text="Timestamp")
                state['listbox'].column("Date", width=140, anchor="center", stretch=False)

                state['listbox'].heading("Type", text="Type")
                state['listbox'].column("Type", width=100, anchor="center", stretch=False)

                state['listbox'].heading("Message Text", text="Message Text")
                state['listbox'].column("Message Text", anchor="e")

                state['listbox'].pack(side="left", fill="both", expand=True)
                scrollbar.config(command=state['listbox'].yview)

                state['listbox'].tag_configure("disabled", foreground=FG_MUTED)

                def on_select_check(event):
                    selected_items = state['listbox'].selection()
                    if not selected_items: return
                    item_id = selected_items[0]
                    tags = state['listbox'].item(item_id, "tags")
                    if "disabled" in tags:
                        state['listbox'].selection_remove(item_id)

                state['listbox'].bind("<<TreeviewSelect>>", on_select_check)

                def on_download():
                    selected_items = state['listbox'].selection()
                    if not selected_items: return
                    item_id = selected_items[0]

                    target_msg = next((m for m in all_msgs if str(m['id']) == item_id), None)

                    if not target_msg or not target_msg['has_media']:
                        messagebox.showwarning("Invalid Selection", "This message does not contain a file or photo.\nPlease select a message marked with 📎 MEDIA.")
                        return

                    state['dl_btn'].config(text="Downloading...", state="disabled")
                    state['load_btn'].config(state="disabled")

                    def on_dl_success(filepath):
                        img_path_var.set(filepath)
                        state['win'].destroy()

                    def on_dl_error(err_msg):
                        state['dl_btn'].config(text="Download & Use", state="normal")
                        state['load_btn'].config(state="normal")
                        messagebox.showerror("Error", f"Failed to download file:\n\n{err_msg}")

                    download_telegram_media_async(dialog_id, target_msg['id'], on_dl_success, on_dl_error)

                btn_frame = tk.Frame(state['win'], bg=BG_MAIN)
                btn_frame.pack(fill="x", padx=10, pady=10)
                state['dl_btn'] = tk.Button(btn_frame, text="Download & Use", command=on_download, bg=BTN_GREEN, fg=FG_MAIN, activebackground="#388e3c", activeforeground="white", font=FONT_SMALL_BOLD, relief="flat", pady=4)
                state['dl_btn'].pack(side="left", expand=True, fill="x", padx=(0, 5))
                state['load_btn'] = tk.Button(btn_frame, text="Load More", command=load_context, bg=BTN_BLUE, fg=FG_MAIN, activebackground="#1976d2", activeforeground="white", font=FONT_SMALL_BOLD, relief="flat", pady=4)
                state['load_btn'].pack(side="right", expand=True, fill="x", padx=(5, 0))

            if not new_msgs:
                if state['load_btn']: state['load_btn'].config(text="No more messages", state="disabled")
                return

            for msg in new_msgs:
                all_msgs.append(msg)
                snippet = msg['text'].replace('\n', ' ')
                # CUTTING STRATEGY: Limit length to 90 chars and append an ellipsis
                if len(snippet) > 90:
                    snippet = snippet[:87] + "..."
                msg_type = "📎 MEDIA" if msg['has_media'] else "💬 TEXT"

                item_tags = ()
                if not msg['has_media']:
                    item_tags = ("disabled",)

                state['listbox'].insert("", tk.END, iid=str(msg['id']), values=(msg['date'], msg_type, snippet), tags=item_tags)

            state['last_id'] = new_msgs[-1]['id']
            if state['load_btn']: state['load_btn'].config(text="Load More", state="normal")

        def on_error(err_msg):
            fetch_img_btn.config(text=fetch_img_btn._original_text, state="normal")
            if state['load_btn']: state['load_btn'].config(text="Load More", state="normal")
            messagebox.showerror("Error", f"Failed to fetch context:\n\n{err_msg}")

        load_context()

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

    tk.Button(submit_frame, text="Start Processing Pipeline", command=on_submit, bg=BTN_GREEN, fg=FG_MAIN, activebackground="#388e3c", activeforeground="white", font=FONT_TITLE, width=30, pady=8, relief="flat").pack(side="right")

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
