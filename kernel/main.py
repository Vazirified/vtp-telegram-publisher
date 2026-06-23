import sys
# Prevent the creation of __pycache__ folders
sys.dont_write_bytecode = True

import os
import shutil
import asyncio
import tkinter as tk
from tkinter import filedialog, messagebox

# --- Import Core Engines ---
try:
    import text_engine
    import image_engine
    import publisher
except ImportError as e:
    print(f"[FATAL] Core module missing: {e}")
    print("Please ensure text_engine.py, image_engine.py, and publisher.py are in the 'kernel' folder.")
    sys.exit(1)

def run_ingestion_gui():
    """
    Launches a native OS window to safely ingest multi-line RTL text
    and browse the local filesystem for the raw image.
    """
    root = tk.Tk()
    root.title("EPLANET Pipeline: Data Ingestion")
    root.geometry("700x550")
    root.configure(padx=20, pady=20)

    # Variables to hold the final data
    payload = {"text": None, "image_path": None}

    # 1. Text Ingestion Section
    tk.Label(root, text="1. Paste Telegram Source Text (Supports RTL & Multi-line):", font=("Arial", 11, "bold")).pack(anchor="w")
    text_input = tk.Text(root, height=15, width=80, font=("Arial", 11), wrap="word")
    text_input.pack(pady=5, fill="both", expand=True)

    # 2. Image Selection Section
    tk.Label(root, text="\n2. Select Raw Image:", font=("Arial", 11, "bold")).pack(anchor="w")

    img_frame = tk.Frame(root)
    img_frame.pack(fill="x", pady=5)

    img_path_var = tk.StringVar()
    img_label = tk.Label(img_frame, textvariable=img_path_var, fg="blue", bg="#f0f0f0", width=65, anchor="w")
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
            messagebox.showerror("Missing Data", "Please paste the source text.")
            return
        if not img_path or not os.path.exists(img_path):
            messagebox.showerror("Missing Data", "Please select a valid raw image file.")
            return

        payload["text"] = raw_text
        payload["image_path"] = img_path
        root.quit()
        root.destroy()

    tk.Button(root, text="Start Processing Pipeline", command=on_submit, bg="#4CAF50", fg="white", font=("Arial", 12, "bold"), pady=10).pack(fill="x", pady=20)

    # Handle window close button (X) gracefully
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

    # Phase 1: GUI Ingestion
    print("\n[~] Launching Data Ingestion Gateway...")
    raw_text, raw_image_path = run_ingestion_gui()

    if not raw_text or not raw_image_path:
        print("[!] Ingestion cancelled or missing data. Aborting pipeline.")
        return

    # Phase 2: Text Core (Translation & Workspace Generation)
    print("\n========================================================")
    print("  PHASE 2: TEXT PROCESSING")
    print("========================================================")
    # Hooks into your existing text execution pipeline[cite: 9]
    session_dir = text_engine.execute_text_pipeline(raw_text)

    if not session_dir or not os.path.exists(session_dir):
        print("[ERROR] Text pipeline failed to generate a session directory. Aborting.")
        return

    # Phase 3: Asset Staging
    print("\n[~] Staging Raw Image Asset...")
    _, ext = os.path.splitext(raw_image_path)
    staged_image_path = os.path.join(session_dir, f"raw_image{ext.lower()}")
    shutil.copy2(raw_image_path, staged_image_path)
    print(f"  [+] Image secured at: {staged_image_path}")

    # Phase 4: Graphics Engine
    print("\n========================================================")
    print("  PHASE 3: GRAPHICS RENDERING")
    print("========================================================")
    # Passes the generated folder directly to your image builder[cite: 6]
    image_engine.render_channel_assets(session_dir)

    # Phase 5: Publishing
    print("\n========================================================")
    print("  PHASE 4: DEPLOYMENT")
    print("========================================================")
    # The publisher automatically detects the latest session[cite: 8]
    # Handle the async event loop natively
    try:
        asyncio.run(publisher.main())
    except KeyboardInterrupt:
        print("\n[!] Publisher terminated by user.")

    print("\n========================================================")
    print("  PIPELINE EXECUTION FINISHED")
    print("========================================================")

if __name__ == "__main__":
    main()
