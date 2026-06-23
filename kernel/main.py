import sys
# Prevent the creation of __pycache__ folders
sys.dont_write_bytecode = True

import os
import shutil
import asyncio
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

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
    root.geometry("800x700")
    root.configure(padx=20, pady=20)

    payload = {"text": None, "image_path": None}

    # --- REUSABLE DIALOG BROWSER ---
    def create_dialog_browser(title, next_step_callback, trigger_btn):
        trigger_btn.config(text="Fetching Chats...", state="disabled")
        all_dialogs = []
        state = {'last_date': None, 'win': None, 'listbox': None, 'load_btn': None}

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
                state['win'].geometry("450x550")

                tk.Label(state['win'], text="Recent Telegram Chats:", font=("Arial", 10, "bold")).pack(anchor="w", pady=(10, 5), padx=10)

                list_frame = tk.Frame(state['win'])
                list_frame.pack(fill="both", expand=True, padx=10, pady=5)
                scrollbar = tk.Scrollbar(list_frame)
                scrollbar.pack(side="right", fill="y")
                state['listbox'] = tk.Listbox(list_frame, font=("Arial", 11), yscrollcommand=scrollbar.set)
                state['listbox'].pack(side="left", fill="both", expand=True)
                scrollbar.config(command=state['listbox'].yview)

                def on_select(event=None):
                    selected_idx = state['listbox'].curselection()
                    if not selected_idx: return
                    selected_dialog = all_dialogs[selected_idx[0]]
                    state['win'].destroy()
                    next_step_callback(selected_dialog['id'], selected_dialog['name'])

                state['listbox'].bind("<Double-Button-1>", on_select)

                btn_frame = tk.Frame(state['win'])
                btn_frame.pack(fill="x", padx=10, pady=10)
                tk.Button(btn_frame, text="View Contents", command=on_select, bg="#4CAF50", fg="white", font=("Arial", 10, "bold")).pack(side="left", expand=True, fill="x", padx=(0, 5))
                state['load_btn'] = tk.Button(btn_frame, text="Load More", command=load_dialogs, bg="#2196F3", fg="white", font=("Arial", 10, "bold"))
                state['load_btn'].pack(side="right", expand=True, fill="x", padx=(5, 0))

            if not new_dialogs:
                if state['load_btn']: state['load_btn'].config(text="No more chats", state="disabled")
                return

            for d in new_dialogs:
                all_dialogs.append(d)
                state['listbox'].insert(tk.END, d['name'])

            state['last_date'] = new_dialogs[-1]['date']
            if state['load_btn']: state['load_btn'].config(text="Load More", state="normal")

        def on_dlg_error(err_msg):
            trigger_btn.config(text=trigger_btn._original_text, state="normal")
            if state['load_btn']: state['load_btn'].config(text="Load More", state="normal")
            messagebox.showerror("Telegram Error", f"Failed to fetch chats:\n\n{err_msg}")

        load_dialogs()


    # ==========================================
    # 1. TEXT INGESTION SECTION
    # ==========================================
    text_header_frame = tk.Frame(root)
    text_header_frame.pack(fill="x", pady=(0, 5))
    tk.Label(text_header_frame, text="1. Source Text (Paste manually or Fetch):", font=("Arial", 11, "bold")).pack(side="left")

    fetch_txt_btn = tk.Button(text_header_frame, text="Fetch Text from Telegram", bg="#e0e0e0", width=22)
    fetch_txt_btn._original_text = "Fetch Text from Telegram"
    fetch_txt_btn.pack(side="right")

    text_input = tk.Text(root, height=15, width=80, font=("Arial", 11), wrap="word")
    text_input.pack(pady=5, fill="both", expand=True)

    def open_message_browser(dialog_id, dialog_name):
        fetch_txt_btn.config(text="Fetching...", state="disabled")
        all_messages = []
        state = {'last_id': 0, 'win': None, 'listbox': None, 'load_btn': None}

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
                state['win'].geometry("750x450")
                tk.Label(state['win'], text="Select messages (Ctrl+Click for multiple):", font=("Arial", 10, "bold")).pack(anchor="w", pady=(10, 5), padx=10)

                list_frame = tk.Frame(state['win'])
                list_frame.pack(fill="both", expand=True, padx=10, pady=5)
                scrollbar = tk.Scrollbar(list_frame)
                scrollbar.pack(side="right", fill="y")
                state['listbox'] = tk.Listbox(list_frame, selectmode=tk.MULTIPLE, font=("Arial", 10), yscrollcommand=scrollbar.set)
                state['listbox'].pack(side="left", fill="both", expand=True)
                scrollbar.config(command=state['listbox'].yview)

                def on_insert():
                    selected_indices = state['listbox'].curselection()
                    if not selected_indices: return
                    for idx in selected_indices:
                        text_input.insert(tk.END, all_messages[idx]['text'] + "\n\n")
                    state['win'].destroy()

                btn_frame = tk.Frame(state['win'])
                btn_frame.pack(fill="x", padx=10, pady=10)
                tk.Button(btn_frame, text="Insert Selected", command=on_insert, bg="#4CAF50", fg="white", font=("Arial", 10, "bold")).pack(side="left", expand=True, fill="x", padx=(0, 5))
                state['load_btn'] = tk.Button(btn_frame, text="Load More", command=load_msgs, bg="#2196F3", fg="white", font=("Arial", 10, "bold"))
                state['load_btn'].pack(side="right", expand=True, fill="x", padx=(5, 0))

            if not new_msgs:
                if state['load_btn']: state['load_btn'].config(text="No more messages", state="disabled")
                return

            for msg in new_msgs:
                all_messages.append(msg)
                preview = msg['text'].replace('\n', ' ')[:100] + "..."
                state['listbox'].insert(tk.END, f"[{msg['date']}] {preview}")

            state['last_id'] = new_msgs[-1]['id']
            if state['load_btn']: state['load_btn'].config(text="Load More", state="normal")

        def on_error(err_msg):
            fetch_txt_btn.config(text=fetch_txt_btn._original_text, state="normal")
            if state['load_btn']: state['load_btn'].config(text="Load More", state="normal")
            messagebox.showerror("Error", f"Failed to fetch:\n\n{err_msg}")

        load_msgs()

    fetch_txt_btn.config(command=lambda: create_dialog_browser("Select Chat for Text", open_message_browser, fetch_txt_btn))


    # ==========================================
    # 2. IMAGE / MEDIA INGESTION SECTION
    # ==========================================
    tk.Label(root, text="\n2. Select Raw Image / File:", font=("Arial", 11, "bold")).pack(anchor="w")

    img_frame = tk.Frame(root)
    img_frame.pack(fill="x", pady=5)

    img_path_var = tk.StringVar()
    # Expand out the label to cleanly push the action buttons to the right side
    img_label = tk.Label(img_frame, textvariable=img_path_var, fg="blue", bg="#f0f0f0", anchor="w")
    img_label.pack(side="left", fill="x", expand=True, padx=(0, 10))

    # A sub-frame anchored right keeps the buttons cleanly grouped
    action_btn_frame = tk.Frame(img_frame)
    action_btn_frame.pack(side="right")

    def browse_image():
        filepath = filedialog.askopenfilename(title="Select Raw Image", filetypes=[("Image Files", "*.png;*.jpg;*.jpeg")])
        if filepath: img_path_var.set(filepath)

    tk.Button(action_btn_frame, text="Browse Local...", command=browse_image, width=15).pack(side="left", padx=(0, 10))

    fetch_img_btn = tk.Button(action_btn_frame, text="Fetch from Telegram", bg="#e0e0e0", width=22)
    fetch_img_btn._original_text = "Fetch from Telegram"
    fetch_img_btn.pack(side="left")

    def open_media_context_browser(dialog_id, dialog_name):
        fetch_img_btn.config(text="Fetching Messages...", state="disabled")
        all_msgs = []
        state = {'last_id': 0, 'win': None, 'listbox': None, 'load_btn': None, 'dl_btn': None}

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
                state['win'].geometry("800x500")
                tk.Label(state['win'], text="Select a message containing a file/photo to download:", font=("Arial", 10, "bold")).pack(anchor="w", pady=(10, 5), padx=10)

                list_frame = tk.Frame(state['win'])
                list_frame.pack(fill="both", expand=True, padx=10, pady=5)
                scrollbar = tk.Scrollbar(list_frame)
                scrollbar.pack(side="right", fill="y")
                state['listbox'] = tk.Listbox(list_frame, selectmode=tk.SINGLE, font=("Arial", 10), yscrollcommand=scrollbar.set)
                state['listbox'].pack(side="left", fill="both", expand=True)
                scrollbar.config(command=state['listbox'].yview)

                def on_download():
                    selected_indices = state['listbox'].curselection()
                    if not selected_indices: return
                    target_msg = all_msgs[selected_indices[0]]

                    if not target_msg['has_media']:
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

                btn_frame = tk.Frame(state['win'])
                btn_frame.pack(fill="x", padx=10, pady=10)
                state['dl_btn'] = tk.Button(btn_frame, text="Download & Use", command=on_download, bg="#4CAF50", fg="white", font=("Arial", 10, "bold"))
                state['dl_btn'].pack(side="left", expand=True, fill="x", padx=(0, 5))
                state['load_btn'] = tk.Button(btn_frame, text="Load More", command=load_context, bg="#2196F3", fg="white", font=("Arial", 10, "bold"))
                state['load_btn'].pack(side="right", expand=True, fill="x", padx=(5, 0))

            if not new_msgs:
                if state['load_btn']: state['load_btn'].config(text="No more messages", state="disabled")
                return

            for msg in new_msgs:
                all_msgs.append(msg)
                snippet = msg['text'][:100] + "..." if len(msg['text']) > 100 else msg['text']
                prefix = "📎 MEDIA:" if msg['has_media'] else "💬 TEXT: "
                state['listbox'].insert(tk.END, f"[{msg['date']}] {prefix} {snippet}")

            state['last_id'] = new_msgs[-1]['id']
            if state['load_btn']: state['load_btn'].config(text="Load More", state="normal")

        def on_error(err_msg):
            fetch_img_btn.config(text=fetch_img_btn._original_text, state="normal")
            if state['load_btn']: state['load_btn'].config(text="Load More", state="normal")
            messagebox.showerror("Error", f"Failed to fetch context:\n\n{err_msg}")

        load_context()

    fetch_img_btn.config(command=lambda: create_dialog_browser("Select Chat for Image", open_media_context_browser, fetch_img_btn))


    # ==========================================
    # 3. SUBMISSION HANDLER
    # ==========================================

    # Sub-frame explicitly used to anchor the Start button to the right
    submit_frame = tk.Frame(root)
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

    # The button is now appropriately sized and pushed to the right side
    tk.Button(submit_frame, text="Start Processing Pipeline", command=on_submit, bg="#4CAF50", fg="white", font=("Arial", 12, "bold"), width=30, pady=8).pack(side="right")

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
