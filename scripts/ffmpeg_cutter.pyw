import json
import os
import re
import subprocess
import sys
import threading
import time
import shutil
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# --- Settings ---
CUTLIST_SUFFIX = ".cutlist.txt"
LOG_FILENAME_TEMPLATE = "ffmpeg_log-{timestamp}.log"
CONFIG_FILE = Path(__file__).parent / "ffmpeg_cutter_config.json"

# --- Cleanup Tool Constants ---
CORRESPONDING_EXTENSIONS = [
    '.cutlist.txt',
    '_adjusted.vdscript',
    '_adjusted_info.txt',
    '_info.txt'
]

EXTRA_FILES = []

ORIGINALS_EXT = [
    '.vdscript',
    '_frame_log.txt'
]

# --- Config Helpers ---
def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_config(data):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Warning: could not save config: {e}")

# --- Helper Functions (Cutter) ---
def parse_timecode_cutlist(cutlist_path):
    segments = []
    pattern = re.compile(r'start_time=([\d.]+),duration=([\d.]+)')
    with open(cutlist_path, 'r') as f:
        for line in f:
            match = pattern.search(line)
            if match:
                segments.append((float(match.group(1)), float(match.group(2))))
    return segments

def run_ffmpeg_command(command, log_file, stop_event):
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1, shell=True) as process:
        for line in process.stdout:
            log_file.write(line)
            log_file.flush()
            if stop_event.is_set():
                process.terminate()
                break
        process.wait()
        return process.returncode

# --- Helper Functions (Cleanup) ---
def move_files(base_folder, files_to_move):
    delete_folder = os.path.join(base_folder, 'delete')
    os.makedirs(delete_folder, exist_ok=True)
    for file_path in files_to_move:
        if os.path.exists(file_path):
            try:
                shutil.move(file_path, delete_folder)
            except Exception as e:
                print(f"Error moving {file_path}: {e}")

def move_folders(base_folder, folders_to_move):
    delete_folder = os.path.join(base_folder, 'delete')
    os.makedirs(delete_folder, exist_ok=True)
    for folder_path in folders_to_move:
        if os.path.exists(folder_path):
            try:
                shutil.move(folder_path, delete_folder)
            except Exception as e:
                print(f"Error moving {folder_path}: {e}")

def get_video_files(folder):
    exts = ('.mp4', '.mkv', '.mov', '.avi', '.ts', '.wmv')
    return [f for f in os.listdir(folder) if f.lower().endswith(exts)]

def collect_corresponding_files(folder, video_files):
    files = []
    for video in video_files:
        base = os.path.join(folder, video)
        for ext in CORRESPONDING_EXTENSIONS:
            f = base + ext
            if os.path.exists(f):
                files.append(f)
    for name in EXTRA_FILES:
        f = os.path.join(folder, name)
        if os.path.exists(f):
            files.append(f)
    for name in os.listdir(folder):
        if name.lower().endswith('.log'):
            f = os.path.join(folder, name)
            if os.path.isfile(f):
                files.append(f)
    return files

def is_system32_path(folder_path):
    if not folder_path or not str(folder_path).strip():
        return False
    try:
        p = Path(folder_path).resolve()
        windir_env = os.environ.get('WINDIR', os.environ.get('SystemRoot', r'C:\Windows'))
        windir = Path(windir_env).resolve()
        sys32 = (windir / 'System32').resolve()
        syswow64 = (windir / 'SysWOW64').resolve()
        if p in (sys32, syswow64, windir):
            return True
        if windir in p.parents and (sys32 in p.parents or syswow64 in p.parents or p == windir):
            return True
        norm = str(p).lower().replace('/', '\\')
        if "\\windows\\system32" in norm or "\\windows\\syswow64" in norm or norm in ("c:\\windows", "c:\\windows\\"):
            return True
    except Exception:
        pass
    return False

def collect_originals(folder, video_files):
    files = []
    for video in video_files:
        base = os.path.join(folder, video)
        for ext in ORIGINALS_EXT:
            f = base + ext
            if os.path.exists(f):
                files.append(f)
    return files

def collect_output_segment_folders(folder, video_files):
    folders = []
    for video in video_files:
        name_no_ext = os.path.splitext(video)[0]
        candidate = os.path.join(folder, name_no_ext)
        if os.path.isdir(candidate):
            folders.append(candidate)
    return folders

# --- Merge / Sanitize Helpers ---
def sanitize_filename(name):
    """Replace any character that isn't alphanumeric, underscore, hyphen, or dot with underscore.
    Collapse consecutive underscores, and strip leading/trailing underscores/hyphens."""
    sanitized = re.sub(r'[^\w\-.]', '_', name)      # replace bad chars
    sanitized = re.sub(r'_+', '_', sanitized)        # collapse runs of underscores
    sanitized = sanitized.strip('_').strip('-')       # strip leading/trailing _ and -
    return sanitized

def find_segment_groups(source_dir):
    """Scan source_dir for subdirectories that contain _part_NNN video files.
    Returns a list of (subdir_path, stem, ext, sorted_part_files).
    """
    video_exts = ('.mp4', '.mkv', '.mov', '.avi', '.ts', '.wmv')
    groups = []
    source_path = Path(source_dir)
    part_pattern = re.compile(r'^(.+)_part_(\d+)(\..+)$', re.IGNORECASE)

    for subdir in sorted(source_path.iterdir()):
        if not subdir.is_dir():
            continue
        parts = []
        stem = None
        ext = None
        for f in subdir.iterdir():
            if f.is_file() and f.suffix.lower() in video_exts:
                m = part_pattern.match(f.name)
                if m:
                    parts.append((int(m.group(2)), f))
                    if stem is None:
                        stem = m.group(1)
                        ext = m.group(3)
        if parts:
            parts.sort(key=lambda x: x[0])
            groups.append((subdir, stem, ext, [p[1] for p in parts]))
    return groups

def merge_group(subdir, stem, ext, part_files, output_dir, log_callback):
    """Concatenate part_files into output_dir/{sanitized_stem}_vffedited{ext} using ffmpeg concat demuxer."""
    sanitized_stem = sanitize_filename(stem)
    out_name = f"{sanitized_stem}_vffedited{ext}"
    output_path = Path(output_dir) / out_name

    # Write concat list
    concat_list_path = subdir / "_concat_list.txt"
    with open(concat_list_path, 'w', encoding='utf-8') as cl:
        for pf in part_files:
            # ffmpeg concat demuxer requires forward slashes
            safe_path = str(pf).replace('\\', '/')
            cl.write(f"file '{safe_path}'\n")

    cmd = (
        f"ffmpeg -f concat -safe 0 -i \"{concat_list_path}\" "
        f"-c copy \"{output_path}\""
    )
    log_callback(f"Merging: {stem}{ext} -> {out_name}\n  CMD: {cmd}\n")

    ret = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    log_callback(ret.stdout)
    log_callback(ret.stderr)

    # Clean up temp concat list
    try:
        concat_list_path.unlink()
    except Exception:
        pass

    if ret.returncode != 0:
        log_callback(f"  ERROR: ffmpeg returned code {ret.returncode}\n")
        return False

    log_callback(f"  Done: {output_path}\n")
    return True

# --- Tooltip Helper ---
class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        widget.bind("<Enter>", self.show_tip)
        widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event=None):
        if self.tip_window or not self.text:
            return
        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 20
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify='left', background="#ffffe0", relief='solid', borderwidth=1, font=("tahoma", "8", "normal"))
        label.pack(ipadx=1)

    def hide_tip(self, event=None):
        tw = self.tip_window
        self.tip_window = None
        if tw:
            tw.destroy()

# --- Main Application Class ---
class FFmpegCutterApp:
    def __init__(self, root, target_folder=""):
        self.root = root
        self.root.title("FFmpeg Cutter (MS Precision Edition)")

        self.start_offset_var = tk.IntVar(value=150)
        self.end_offset_var = tk.IntVar(value=1000)
        self.audio_mode_var = tk.StringVar(value="Copy")
        self.audio_bitrate_var = tk.StringVar(value="128")
        self.container_mode_var = tk.StringVar(value="Same as source")

        self.progress_var = tk.DoubleVar()
        self.time_remaining_var = tk.StringVar(value="")
        self.stop_event = threading.Event()

        if target_folder and Path(target_folder).is_dir() and not is_system32_path(target_folder):
            folder_val = target_folder
        elif not is_system32_path(str(Path.cwd())):
            folder_val = str(Path.cwd())
        else:
            folder_val = ""
        self.selected_dir_var = tk.StringVar(value=folder_val)

        self.build_ui()
        self.add_top_buttons()

    def build_ui(self):
        padding = {"padx": 5, "pady": 5}
        frame = ttk.Frame(self.root)
        frame.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Source Folder:").grid(row=0, column=0, sticky=tk.W, **padding)
        self.dir_entry = ttk.Entry(frame, textvariable=self.selected_dir_var, state="readonly", width=40)
        self.dir_entry.grid(row=0, column=1, columnspan=2, sticky=(tk.W, tk.E), **padding)
        self.browse_btn = ttk.Button(frame, text="Browse", command=self.browse_source_folder)
        self.browse_btn.grid(row=0, column=3, sticky=tk.W, **padding)

        ttk.Label(frame, text="Start Offset (ms):").grid(row=1, column=0, sticky=tk.W, **padding)
        self.start_entry = ttk.Entry(frame, textvariable=self.start_offset_var, width=6)
        self.start_entry.grid(row=1, column=1, sticky=tk.W, **padding)
        ToolTip(self.start_entry, "Seek Nudge: Pushes the seek point forward (e.g., 150 ms).")

        ttk.Label(frame, text="End Offset (ms):").grid(row=1, column=2, sticky=tk.W, **padding)
        self.end_entry = ttk.Entry(frame, textvariable=self.end_offset_var, width=6)
        self.end_entry.grid(row=1, column=3, sticky=tk.W, **padding)
        ToolTip(self.end_entry, "Safety Buffer: Adds extra duration to the end (e.g., 1000 ms).")

        ttk.Label(frame, text="Audio Mode:").grid(row=2, column=0, sticky=tk.W, **padding)
        self.audio_menu = ttk.Combobox(frame, textvariable=self.audio_mode_var, values=["Copy", "AAC", "MP3", "WAV"], state="readonly", width=10)
        self.audio_menu.grid(row=2, column=1, sticky=tk.W, **padding)
        self.audio_menu.bind("<<ComboboxSelected>>", self.on_audio_mode_change)

        self.bitrate_label = ttk.Label(frame, text="Bitrate (kbps):")
        self.bitrate_label.grid(row=2, column=2, sticky=tk.W, **padding)

        self.bitrate_menu = ttk.Combobox(frame, textvariable=self.audio_bitrate_var, values=["128", "160", "192"], state="readonly", width=6)
        self.bitrate_menu.grid(row=2, column=3, sticky=tk.W, **padding)

        ttk.Label(frame, text="Output Container:").grid(row=3, column=0, sticky=tk.W, **padding)
        self.container_menu = ttk.Combobox(frame, textvariable=self.container_mode_var, values=["Same as source", "MP4", "MOV", "MKV"], state="readonly", width=15)
        self.container_menu.grid(row=3, column=1, columnspan=3, sticky=tk.W, **padding)
        self.container_menu.bind("<<ComboboxSelected>>", self.on_container_mode_change)

        ttk.Button(frame, text="Start Cutting", command=self.start_cutting).grid(row=4, column=0, pady=10)
        ttk.Button(frame, text="Cancel", command=self.cancel_processing).grid(row=4, column=1, pady=10)

        ttk.Progressbar(frame, variable=self.progress_var, maximum=100).grid(row=5, column=0, columnspan=4, sticky="we", **padding)
        ttk.Label(frame, textvariable=self.time_remaining_var).grid(row=6, column=0, columnspan=4, sticky=tk.W, **padding)

        self.on_audio_mode_change()

    def on_audio_mode_change(self, *args):
        self.toggle_bitrate_visibility()
        self.toggle_container_for_wav()

    def on_container_mode_change(self, *args):
        pass

    def toggle_bitrate_visibility(self):
        mode = self.audio_mode_var.get().lower()
        if mode in ["copy", "wav"]:
            self.bitrate_label.grid_remove()
            self.bitrate_menu.grid_remove()
        else:
            self.bitrate_label.grid()
            self.bitrate_menu.grid()

    def toggle_container_for_wav(self):
        if self.audio_mode_var.get() == "WAV":
            if self.container_mode_var.get() != "MKV":
                self.container_mode_var.set("MKV")
            self.container_menu.config(state="disabled")
        else:
            self.container_menu.config(state="readonly")

    def cancel_processing(self):
        self.stop_event.set()

    def browse_source_folder(self):
        init_dir = self.selected_dir_var.get()
        if is_system32_path(init_dir) or not os.path.isdir(init_dir):
            init_dir = ""
        folder = filedialog.askdirectory(initialdir=init_dir, title="Select Source Folder", parent=self.root)
        if folder:
            self.selected_dir_var.set(folder)

    def start_cutting(self):
        threading.Thread(target=self.process_cutlists).start()

    def process_cutlists(self):
        source_dir = Path(self.selected_dir_var.get())
        if not source_dir.is_dir():
            messagebox.showerror("Error", "Invalid source folder.")
            return

        cutlist_files = [f for f in source_dir.iterdir() if f.name.endswith(CUTLIST_SUFFIX)]
        if not cutlist_files:
            messagebox.showerror("Error", f"No '{CUTLIST_SUFFIX}' files found.")
            return

        timestamp = datetime.now().strftime("%y-%m-%d_%H-%M-%S")
        log_file_path = source_dir / LOG_FILENAME_TEMPLATE.format(timestamp=timestamp)
        
        total_segments = 0
        for cutlist_file in cutlist_files:
            segments = parse_timecode_cutlist(cutlist_file)
            total_segments += len(segments)

        if total_segments == 0:
            messagebox.showinfo("Info", "No valid segments found.")
            return

        self.progress_var.set(0)
        self.time_remaining_var.set("")
        processed_segments = 0
        start_time = time.time()

        with open(log_file_path, "w", encoding="utf-8") as log_file:
            for cutlist_path in cutlist_files:
                if self.stop_event.is_set(): break

                input_file_name = cutlist_path.name.replace(CUTLIST_SUFFIX, "")
                input_file = source_dir / input_file_name
                
                if not input_file.exists():
                    log_file.write(f"Missing input file: {input_file}\n")
                    continue

                segments = parse_timecode_cutlist(cutlist_path)
                
                time_offset_start = self.start_offset_var.get() / 1000.0
                time_offset_end = self.end_offset_var.get() / 1000.0

                output_dir = source_dir / input_file.stem
                output_dir.mkdir(parents=True, exist_ok=True)

                output_container = self.container_mode_var.get()
                ext = input_file.suffix if output_container == "Same as source" else f".{output_container.lower()}"
                
                audio_mode = self.audio_mode_var.get().lower()
                if audio_mode == "copy": audio_flag = "-c:a copy"
                elif audio_mode == "wav": audio_flag = "-c:a pcm_s16le"
                else: audio_flag = f"-c:a {audio_mode} -b:a {self.audio_bitrate_var.get()}k"

                for i, (start_ts, duration) in enumerate(segments):
                    if self.stop_event.is_set(): break

                    adj_start = start_ts + time_offset_start
                    adj_end = start_ts + duration + time_offset_end
                    adj_duration = adj_end - adj_start

                    output_file = output_dir / f"{input_file.stem}_part_{i+1:03d}{ext}"
                    cmd = (
                        f"ffmpeg -ss {adj_start:.6f} -i \"{input_file}\" -t {adj_duration:.6f} "
                        f"-c:v copy {audio_flag} -avoid_negative_ts make_zero \"{output_file}\""
                    )
                    
                    log_file.write(f"Seg {i+1}: {cmd}\n")
                    run_ffmpeg_command(cmd, log_file, self.stop_event)
                    
                    processed_segments += 1
                    self.progress_var.set((processed_segments / total_segments) * 100)
                    
                    elapsed = time.time() - start_time
                    if processed_segments > 0:
                        rate = elapsed / processed_segments
                        remaining = (total_segments - processed_segments) * rate
                        self.time_remaining_var.set(f"Remaining: {int(remaining)}s")

        self.time_remaining_var.set("Done.")
        if not self.stop_event.is_set():
            self.root.after(0, lambda: self._prompt_merge_after_cut(
                processed_segments, log_file_path.name, str(source_dir)
            ))
        self.stop_event.clear()

    def _prompt_merge_after_cut(self, processed_segments, log_name, source_dir_str):
        """Show a completion dialog that offers to open the Merge tool (Yes default)."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Completed")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(
            dialog,
            text=f"Processed {processed_segments} segments.\nLog: {log_name}",
            padding=(20, 15, 20, 5)
        ).pack()
        ttk.Separator(dialog, orient="horizontal").pack(fill="x", padx=10)
        ttk.Label(
            dialog,
            text="Would you like to merge the segments?",
            padding=(20, 10, 20, 5)
        ).pack()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=(5, 15))

        def on_yes():
            dialog.destroy()
            MergeToolWindow(self.root, source_dir_str)

        def on_no():
            dialog.destroy()

        yes_btn = ttk.Button(btn_frame, text="Yes", command=on_yes, width=8)
        yes_btn.pack(side="left", padx=(0, 8))
        ttk.Button(btn_frame, text="No", command=on_no, width=8).pack(side="left")

        # Centre the dialog over the root window
        dialog.update_idletasks()
        rw = self.root.winfo_rootx() + self.root.winfo_width() // 2
        rh = self.root.winfo_rooty() + self.root.winfo_height() // 2
        dw = dialog.winfo_width()
        dh = dialog.winfo_height()
        dialog.geometry(f"+{rw - dw // 2}+{rh - dh // 2}")

        yes_btn.focus_set()  # Yes is focused / default
        dialog.bind("<Return>", lambda e: on_yes())
        dialog.bind("<Escape>", lambda e: on_no())

    def add_top_buttons(self):
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(anchor="ne", padx=10, pady=5)

        merge_button = ttk.Button(btn_frame, text="Merge", command=self.open_merge)
        merge_button.pack(side="left", padx=(0, 5))

        cleanup_button = ttk.Button(btn_frame, text="Cleanup", command=self.open_cleanup)
        cleanup_button.pack(side="left", padx=(0, 5))

        help_button = ttk.Button(btn_frame, text="? Help", command=self.show_help)
        help_button.pack(side="left")

    def open_merge(self):
        MergeToolWindow(self.root, self.selected_dir_var.get())

    def open_cleanup(self):
        CleanupToolWindow(self.root, self.selected_dir_var.get())

    def show_help(self):
        msg = """FFmpeg Cutter (MS Precision Edition)
-------------------------------------------------------------
HOW TO USE:
1. Ensure your folder contains video files and corresponding .cutlist.txt files.
2. Select the folder above.
3. Choose Audio/Container settings and click 'Start Cutting'.

-------------------------------------------------------------
UNDERSTANDING OFFSETS (MILLISECONDS):
This tool uses TIME (ms) for maximum precision. 1000 ms = 1 Second.

START OFFSET (The "Seek Nudge"):
- This is NOT a buffer; it pushes the seek point slightly forward.
- Since your cutlists are keyframe-aligned, this 'nudge' ensures 
  FFmpeg snaps to the correct keyframe rather than the previous one.
- Recommended: 100ms to 300ms. (0ms will cause approx 10s of unwanted video in many of the output segments).

END OFFSET (The "Safety Buffer"):
- This adds extra duration to the end of the segment.
- Use this to ensure a scene isn't cut too abruptly.
- Recommended: 1000ms (1 second).

-------------------------------------------------------------
Audio Modes:
- Copy: Losslessly copies the audio stream. No re-encoding. Bitrate not applicable.
- AAC / MP3: Re-encodes audio to the selected lossy format at a specified bitrate.
- WAV: Re-encodes audio to uncompressed WAV (PCM). Bitrate not applicable.
  *Note: When WAV audio is selected, the output container will automatically be set to MKV,
  as WAV is most reliably supported in the MKV container.*

Configuration:
Default values can be changed by editing this file. Look for:

    self.start_offset_var = tk.IntVar(value=150)
    self.end_offset_var = tk.IntVar(value=1000)
    self.audio_mode_var = tk.StringVar(value="Copy")
    self.audio_bitrate_var = tk.StringVar(value="128")
    self.container_mode_var = tk.StringVar(value="Same as source")
"""
        help_win = tk.Toplevel(self.root)
        help_win.title("FFmpeg Cutter Help")
        help_win.geometry("520x600")
        help_win.transient(self.root)
        
        text_area = tk.Text(help_win, wrap="word", padx=10, pady=10, font=("Consolas", 9))
        text_area.insert("1.0", msg)
        text_area.config(state="disabled")
        
        scrollbar = ttk.Scrollbar(help_win, command=text_area.yview)
        text_area.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side="right", fill="y")
        text_area.pack(side="left", fill="both", expand=True)


# --- Merge Tool Window Class ---
class MergeToolWindow:
    def __init__(self, master, default_source_dir):
        self.window = tk.Toplevel(master)
        self.window.title("Merge Segments")
        self.window.geometry("600x520")
        self.window.transient(master)
        self.window.resizable(True, True)

        self.source_dir = tk.StringVar(value="" if is_system32_path(default_source_dir) else default_source_dir)

        # Load persisted merge output dir
        cfg = load_config()
        saved_merge_dir = cfg.get("merge_output_dir", "")
        if saved_merge_dir and os.path.isdir(saved_merge_dir):
            merge_dir_val = saved_merge_dir
        else:
            merge_dir_val = ""
        self.merge_output_dir = tk.StringVar(value=merge_dir_val)

        self.build_ui()
        self._refresh_preview()

    def build_ui(self):
        padding = {"padx": 10, "pady": 4}
        main = ttk.Frame(self.window)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # --- Source folder ---
        ttk.Label(main, text="Source Folder (containing segment subfolders):").grid(
            row=0, column=0, columnspan=3, sticky=tk.W, **padding)
        ttk.Entry(main, textvariable=self.source_dir, state="readonly", width=52).grid(
            row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), **padding)
        ttk.Button(main, text="Browse", command=self.browse_source).grid(
            row=1, column=2, sticky=tk.W, **padding)

        # --- Merge output folder ---
        ttk.Label(main, text="Merged Output Folder:").grid(
            row=2, column=0, columnspan=3, sticky=tk.W, padx=10, pady=(10, 2))
        ttk.Entry(main, textvariable=self.merge_output_dir, state="readonly", width=52).grid(
            row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), **padding)
        ttk.Button(main, text="Browse", command=self.browse_output).grid(
            row=3, column=2, sticky=tk.W, **padding)

        # --- Preview label ---
        ttk.Label(main, text="Segments found (preview):").grid(
            row=4, column=0, columnspan=3, sticky=tk.W, padx=10, pady=(10, 2))

        # --- Preview text box ---
        preview_frame = ttk.Frame(main)
        preview_frame.grid(row=5, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), padx=10, pady=2)
        main.rowconfigure(5, weight=1)
        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)

        self.preview_text = tk.Text(
            preview_frame, wrap="none", height=10,
            font=("Consolas", 9), state="disabled", bg="#f8f8f8")
        sb_y = ttk.Scrollbar(preview_frame, orient="vertical", command=self.preview_text.yview)
        sb_x = ttk.Scrollbar(preview_frame, orient="horizontal", command=self.preview_text.xview)
        self.preview_text.configure(yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)
        sb_y.pack(side="right", fill="y")
        sb_x.pack(side="bottom", fill="x")
        self.preview_text.pack(side="left", fill="both", expand=True)

        # --- Refresh & Merge buttons ---
        btn_row = ttk.Frame(main)
        btn_row.grid(row=6, column=0, columnspan=3, sticky=tk.W, padx=10, pady=8)
        ttk.Button(btn_row, text="Refresh Preview", command=self._refresh_preview).pack(side="left", padx=(0, 8))
        self.merge_btn = ttk.Button(btn_row, text="Merge All", command=self._start_merge)
        self.merge_btn.pack(side="left")

        # --- Status label ---
        self.status_var = tk.StringVar(value="")
        ttk.Label(main, textvariable=self.status_var, wraplength=560).grid(
            row=7, column=0, columnspan=3, sticky=tk.W, padx=10, pady=(0, 4))

        # Trace changes to source_dir
        self.source_dir.trace_add("write", lambda *a: self._refresh_preview())

    def browse_source(self):
        init = self.source_dir.get()
        if is_system32_path(init) or not os.path.isdir(init):
            init = ""
        folder = filedialog.askdirectory(initialdir=init, title="Select Source Folder", parent=self.window)
        if folder:
            self.source_dir.set(folder)

    def browse_output(self):
        init = self.merge_output_dir.get()
        if is_system32_path(init) or not os.path.isdir(init):
            init = ""
        folder = filedialog.askdirectory(initialdir=init, title="Select Merged Output Folder", parent=self.window)
        if folder:
            self.merge_output_dir.set(folder)
            # Persist the chosen folder immediately
            cfg = load_config()
            cfg["merge_output_dir"] = folder
            save_config(cfg)

    def _refresh_preview(self):
        src = self.source_dir.get()
        self.preview_text.config(state="normal")
        self.preview_text.delete("1.0", "end")

        if not src or not os.path.isdir(src):
            self.preview_text.insert("end", "No valid source folder selected.")
            self.preview_text.config(state="disabled")
            self.merge_btn.config(state="disabled")
            return

        groups = find_segment_groups(src)
        if not groups:
            self.preview_text.insert(
                "end",
                "No segment subfolders found.\n\n"
                "Expected subfolders containing files like:\n"
                "  my_vacation_part_001.mp4\n"
                "  my_vacation_part_002.mp4"
            )
            self.preview_text.config(state="disabled")
            self.merge_btn.config(state="disabled")
            return

        for subdir, stem, ext, parts in groups:
            sanitized = sanitize_filename(stem)
            out_name = f"{sanitized}_vffedited{ext}"
            self.preview_text.insert("end", f"[{subdir.name}/]\n")
            for pf in parts:
                self.preview_text.insert("end", f"    {pf.name}\n")
            self.preview_text.insert("end", f"  -> {out_name}\n\n")

        self.preview_text.config(state="disabled")
        self.merge_btn.config(state="normal")

    def _start_merge(self):
        src = self.source_dir.get()
        out_dir = self.merge_output_dir.get()

        if not src or not os.path.isdir(src):
            messagebox.showerror("Error", "Please select a valid source folder.", parent=self.window)
            return
        if not out_dir or not os.path.isdir(out_dir):
            messagebox.showerror("Error", "Please select a valid merge output folder.", parent=self.window)
            return

        groups = find_segment_groups(src)
        if not groups:
            messagebox.showinfo("Info", "No segment groups found to merge.", parent=self.window)
            return

        # Check for files that would be overwritten
        existing = []
        for subdir, stem, ext, parts in groups:
            out_name = f"{sanitize_filename(stem)}_vffedited{ext}"
            out_path = Path(out_dir) / out_name
            if out_path.exists():
                existing.append(out_name)

        if existing:
            file_list = "\n".join(f"  {n}" for n in existing)
            answer = messagebox.askyesno(
                "Overwrite?",
                f"The following file(s) already exist in the output folder:\n\n"
                f"{file_list}\n\n"
                f"Do you want to overwrite them?",
                parent=self.window
            )
            if not answer:
                return

        self.merge_btn.config(state="disabled")
        self.status_var.set("Merging... please wait.")
        threading.Thread(target=self._merge_worker, args=(groups, out_dir), daemon=True).start()

    def _merge_worker(self, groups, out_dir):
        log_lines = []
        success = 0
        errors = 0

        def log_cb(msg):
            log_lines.append(msg)

        for subdir, stem, ext, parts in groups:
            ok = merge_group(subdir, stem, ext, parts, out_dir, log_cb)
            if ok:
                success += 1
            else:
                errors += 1

        # Write log to output folder
        timestamp = datetime.now().strftime("%y-%m-%d_%H-%M-%S")
        log_path = Path(out_dir) / f"merge_log-{timestamp}.log"
        try:
            with open(log_path, 'w', encoding='utf-8') as lf:
                lf.write("".join(log_lines))
        except Exception as e:
            log_lines.append(f"Could not write log: {e}\n")

        summary = f"Merge complete: {success} succeeded, {errors} failed.\nLog: {log_path.name}"
        self.window.after(0, lambda: self._merge_done(summary))

    def _merge_done(self, summary):
        self.status_var.set(summary)
        self.merge_btn.config(state="normal")
        messagebox.showinfo("Merge Complete", summary, parent=self.window)


# --- Cleanup Tool Window Class ---
class CleanupToolWindow:
    def __init__(self, master, default_dir):
        self.window = tk.Toplevel(master)
        self.window.title("Cleanup Tool")
        self.window.geometry("520x330")
        self.window.transient(master)

        init_dir = "" if is_system32_path(default_dir) else default_dir
        self.folder = tk.StringVar(value=init_dir)
        self.remove_output_segments = tk.BooleanVar()
        self.remove_originals = tk.BooleanVar()

        self.build_ui()
        self.folder.trace_add("write", lambda *args: self.validate_folder())
        self.validate_folder()

    def build_ui(self):
        padding = {"padx": 15, "pady": 5}
        ttk.Label(self.window, text="Select folder to clean:").pack(anchor="w", **padding)
        frame = ttk.Frame(self.window)
        frame.pack(fill="x", padx=15)
        ttk.Entry(frame, textvariable=self.folder, width=50).pack(side="left", expand=1, fill="x")
        ttk.Button(frame, text="Browse", command=self.browse_folder).pack(side="right", padx=(5,0))

        self.status_label = ttk.Label(self.window, text="", font=("Segoe UI", 9, "bold"))
        self.status_label.pack(anchor="w", padx=15, pady=(4, 0))

        chk_frame = ttk.Frame(self.window)
        chk_frame.pack(fill="both", expand=True, padx=15, pady=10)
        ttk.Checkbutton(chk_frame, text="Remove output segments", variable=self.remove_output_segments).pack(anchor="w", pady=2)
        tk.Checkbutton(chk_frame, text="Remove original vdscripts & frame logs - CAUTION", variable=self.remove_originals, fg="darkred").pack(anchor="w", pady=(8, 2))

        btn_frame = ttk.Frame(self.window)
        btn_frame.pack(fill="x", padx=15, pady=10)
        self.run_button = ttk.Button(btn_frame, text="Run Cleanup", command=self.cleanup)
        self.run_button.pack(side="left")
        ttk.Button(btn_frame, text="Help", command=self.show_help).pack(side="right")

    def validate_folder(self):
        folder = self.folder.get().strip()
        if not folder:
            self.status_label.config(text="No folder selected.", foreground="#888888")
            self.run_button.config(state="disabled")
        elif is_system32_path(folder):
            self.status_label.config(text="Cleanup is disabled for system directory (System32).", foreground="red")
            self.run_button.config(state="disabled")
        elif not os.path.isdir(folder):
            self.status_label.config(text="Selected path is not a valid directory.", foreground="#d9534f")
            self.run_button.config(state="disabled")
        else:
            self.status_label.config(text="")
            self.run_button.config(state="normal")

    def browse_folder(self):
        init_dir = self.folder.get().strip()
        if is_system32_path(init_dir) or not os.path.isdir(init_dir):
            init_dir = ""
        folder = filedialog.askdirectory(initialdir=init_dir, title="Select Folder to Clean", parent=self.window)
        if folder:
            self.folder.set(folder)

    def cleanup(self):
        folder = self.folder.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror("Error", "Please select a valid folder.", parent=self.window)
            return
        if is_system32_path(folder):
            messagebox.showerror("Error", "Cleanup cannot be run on a system directory.", parent=self.window)
            return

        video_files = get_video_files(folder)
        files_to_move = collect_corresponding_files(folder, video_files)
        
        folders_to_move = []
        if self.remove_output_segments.get():
            segs = collect_output_segment_folders(folder, video_files)
            if segs and messagebox.askyesno("Warning", "Move segments to delete folder?", parent=self.window):
                folders_to_move += segs
        
        if self.remove_originals.get():
            origs = collect_originals(folder, video_files)
            if origs and messagebox.askyesno("Warning", "Move originals? Recreating them can take a long time!", parent=self.window):
                files_to_move += origs

        if not files_to_move and not folders_to_move:
            messagebox.showinfo("Cleanup", "No cleanup files or folders found to move.", parent=self.window)
            return

        if files_to_move:
            move_files(folder, files_to_move)
        if folders_to_move:
            move_folders(folder, folders_to_move)
        messagebox.showinfo("Cleanup", "Done.", parent=self.window)

    def show_help(self):
        help_text = (
            "Cleanup Tool — Help\n\n"
            "This tool helps you declutter folders containing video projects created using the VffEdit workflow.\n\n"
            "Default behaviour (no boxes checked):\n"
            "- Moves temporary/output files that sit next to your video files into a 'delete' subfolder.\n"
            "- These include files like .cutlist.txt, *_adjusted.vdscript, *_adjusted_info.txt, *_info.txt.\n"
            "- Also moves all .log files found in the folder.\n"
            "- Original video files (.mp4, .mkv, .mov, etc.) are NEVER moved.\n\n"
            "\"Remove output segments\" checkbox:\n"
            "- If checked, looks for folders named after each video (e.g. 'whatever' for 'whatever.mp4').\n"
            "- These folders are assumed to contain the FFmpeg Cutter output segments.\n"
            "- A warning is shown first: only proceed if you have already merged the segments you need.\n\n"
            "\"Remove original vdscripts & frame logs - CAUTION\" checkbox:\n"
            "- If checked, moves original .vdscript files and *_frame_log.txt files into 'delete'.\n"
            "- WARNING: These original VirtualDub2 cutlists and frame logs can take a VERY long time to recreate.\n"
            "- Use this option only when you are absolutely sure you no longer need the originals.\n"
            "- The tool always shows a confirmation warning before moving them.\n\n"
            "Usage:\n"
            "1. Select your folder with the Browse button.\n"
            "2. Choose which checkboxes you want.\n"
            "3. Click Run Cleanup.\n"
            "4. Inspect the 'delete' folder before permanently deleting anything."
        )
        help_win = tk.Toplevel(self.window)
        help_win.title("Cleanup Tool Help")
        help_win.geometry("500x550")
        help_win.transient(self.window)
        
        text_area = tk.Text(help_win, wrap="word", padx=10, pady=10, font=("Consolas", 9))
        text_area.insert("1.0", help_text)
        text_area.config(state="disabled")
        
        scrollbar = ttk.Scrollbar(help_win, command=text_area.yview)
        text_area.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side="right", fill="y")
        text_area.pack(side="left", fill="both", expand=True)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else ""
    root = tk.Tk()
    app = FFmpegCutterApp(root, target)
    root.mainloop()