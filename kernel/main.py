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
    print("Please ensure auth_manager.py, text_engine.py, image_engine.py, and publisher.py are in the 'kernel' folder.")
    sys.exit(1)

def fetch_telegram_dialogs_async(callback, error_callback, offset_date=None):
    """Fetches the 30 most recent chats/dialogs, supporting pagination via offset_date."""
    def run_async():
        async def fetch():
            client = auth_manager.get_client()
            if not client:
                return None
            dialogs_data = []
            try:
                await client.start()
                kwargs = {'limit': 30}
                if offset_date:
                    kwargs['offset_date'] = offset_date

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
    """Fetches the last 20 messages from the selected dialog ID, supporting pagination via offset_id."""
    def run_async():
        async def fetch():
            client = auth_manager.get_client()
            if not client:
                return None
            messages = []
            try:
                await client.start()
                entity = await client.get_entity(target_entity_id)
                kwargs = {'limit': 20}
                if offset_id:
                    kwargs['offset_id'] = offset_id

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

        if isinstance(result, str):
            error_callback(result)
        else:
            callback(result)

    threading.Thread(target=run_async, daemon=True).start()

def run_ingestion_gui():
    root = tk.Tk()
    root.title("EPLANET Pipeline: Data Ingestion")
    root.geometry("750x650")
    root.configure(padx=20, pady=20)

    payload = {"text": None, "image_path": None}

    # 1. Text Ingestion Section
    header_frame = tk.Frame(root)
    header_frame.pack(fill="x", pady=(0, 5))

    tk.Label(header_frame, text="1. Source Text (Paste manually or Fetch from Telegram):", font=("Arial", 11, "bold")).pack(side="left")

    text_input = tk.Text(root, height=15, width=80, font=("Arial", 11), wrap="word")
    text_input.pack(pady=5, fill="both", expand=True)

    # --- TELEGRAM UI LOGIC ---
    def open_message_browser(dialog_id, dialog_name):
        fetch_btn.config(text="Fetching Messages...", state="disabled")

        all_messages = []
        state = {'last_id': 0, 'win': None, 'listbox': None, 'load_btn': None}

        def load_messages():
            if state['load_btn']:
                state['load_btn'].config(text="Loading...", state="disabled")
            fetch_telegram_messages_async(dialog_id, on_msg_success, on_msg_error, offset_id=state['last_id'])

        def on_msg_success(new_messages):
            fetch_btn.config(text="Fetch Telegram Messages", state="normal")

            # Initialize Window on First Fetch
            if not state['win']:
                if not new_messages:
                    messagebox.showinfo("Telegram", f"No text messages found in {dialog_name}.")
                    return

                state['win'] = tk.Toplevel(root)
                state['win'].title(f"Messages from: {dialog_name}")
                state['win'].geometry("750x450")

                tk.Label(state['win'], text="Select messages to import (Ctrl+Click for multiple):", font=("Arial", 10, "bold")).pack(anchor="w", pady=(10, 5), padx=10)

                # Setup Listbox with Scrollbar
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

                # Action Buttons
                btn_frame = tk.Frame(state['win'])
                btn_frame.pack(fill="x", padx=10, pady=10)
                tk.Button(btn_frame, text="Insert Selected", command=on_insert, bg="#4CAF50", fg="white", font=("Arial", 10, "bold")).pack(side="left", expand=True, fill="x", padx=(0, 5))
                state['load_btn'] = tk.Button(btn_frame, text="Load More", command=load_messages, bg="#2196F3", fg="white", font=("Arial", 10, "bold"))
                state['load_btn'].pack(side="right", expand=True, fill="x", padx=(5, 0))

            # Handle Empty Returns
            if not new_messages:
                if state['load_btn']:
                    state['load_btn'].config(text="No more messages", state="disabled")
                return

            # Append New Messages
            for msg in new_messages:
                all_messages.append(msg)
                preview = msg['text'].replace('\n', ' ')[:100] + "..."
                state['listbox'].insert(tk.END, f"[{msg['date']}] {preview}")

            # Update Pagination Tracker
            state['last_id'] = new_messages[-1]['id']
            if state['load_btn']:
                state['load_btn'].config(text="Load More", state="normal")

        def on_msg_error(err_msg):
            fetch_btn.config(text="Fetch Telegram Messages", state="normal")
            if state['load_btn']:
                state['load_btn'].config(text="Load More", state="normal")
            messagebox.showerror("Error", f"Failed to fetch messages:\n\n{err_msg}")

        # Start initial fetch
        load_messages()

    def trigger_dialog_browser():
        fetch_btn.config(text="Fetching Chats...", state="disabled")

        all_dialogs = []
        state = {'last_date': None, 'win': None, 'listbox': None, 'load_btn': None}

        def load_dialogs():
            if state['load_btn']:
                state['load_btn'].config(text="Loading...", state="disabled")
            fetch_telegram_dialogs_async(on_dlg_success, on_dlg_error, offset_date=state['last_date'])

        def on_dlg_success(new_dialogs):
            fetch_btn.config(text="Fetch Telegram Messages", state="normal")

            # Initialize Window on First Fetch
            if not state['win']:
                if not new_dialogs:
                    messagebox.showerror("Error", "Could not find any recent chats.")
                    return

                state['win'] = tk.Toplevel(root)
                state['win'].title("Select Telegram Chat")
                state['win'].geometry("450x550")

                tk.Label(state['win'], text="Recent Telegram Chats:", font=("Arial", 10, "bold")).pack(anchor="w", pady=(10, 5), padx=10)

                # Setup Listbox with Scrollbar
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
                    open_message_browser(selected_dialog['id'], selected_dialog['name'])

                state['listbox'].bind("<Double-Button-1>", on_select)

                # Action Buttons
                btn_frame = tk.Frame(state['win'])
                btn_frame.pack(fill="x", padx=10, pady=10)
                tk.Button(btn_frame, text="View Messages", command=on_select, bg="#4CAF50", fg="white", font=("Arial", 10, "bold")).pack(side="left", expand=True, fill="x", padx=(0, 5))
                state['load_btn'] = tk.Button(btn_frame, text="Load More", command=load_dialogs, bg="#2196F3", fg="white", font=("Arial", 10, "bold"))
                state['load_btn'].pack(side="right", expand=True, fill="x", padx=(5, 0))

            # Handle Empty Returns
            if not new_dialogs:
                if state['load_btn']:
                    state['load_btn'].config(text="No more chats", state="disabled")
                return

            # Append New Dialogs
            for d in new_dialogs:
                all_dialogs.append(d)
                state['listbox'].insert(tk.END, d['name'])

            # Update Pagination Tracker
            state['last_date'] = new_dialogs[-1]['date']
            if state['load_btn']:
                state['load_btn'].config(text="Load More", state="normal")

        def on_dlg_error(err_msg):
            fetch_btn.config(text="Fetch Telegram Messages", state="normal")
            if state['load_btn']:
                state['load_btn'].config(text="Load More", state="normal")
            messagebox.showerror("Telegram Error", f"Failed to fetch chats:\n\n{err_msg}")

        # Start initial fetch
        load_dialogs()

    fetch_btn = tk.Button(header_frame, text="Fetch Telegram Messages", command=trigger_dialog_browser, bg="#e0e0e0")
    fetch_btn.pack(side="right")

    # 2. Image Selection Section
    tk.Label(root, text="\n2. Select Raw Image:", font=("Arial", 11, "bold")).pack(anchor="w")

    img_frame = tk.Frame(root)
    img_frame.pack(fill="x", pady=5)

    img_path_var = tk.StringVar()
    img_label = tk.Label(img_frame, textvariable=img_path_var, fg="blue", bg="#f0f0f0", width=70, anchor="w")
    img_label.pack(side="left", padx=(0, 10))

    def browse_image():
        filepath = filedialog.askopenfilename(
            title="Select Raw Image",
            filetypes=[("Image Files", "*.png;*.jpg;*.jpeg")]
        )
        if filepath:
            img_path_var.set(filepath)

    tk.Button(img_frame, text="Browse...", command=browse_image, width=10).pack(side="left")

    # 3. Submission Handler
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

    tk.Button(root, text="Start Processing Pipeline", command=on_submit, bg="#4CAF50", fg="white", font=("Arial", 12, "bold"), pady=10).pack(fill="x", pady=20)

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
