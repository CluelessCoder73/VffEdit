import os
import re
import subprocess
import threading
import time
import json
import shutil
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# --- Settings ---
CUTLIST_SUFFIX = ".cutlist.txt"
LOG_FILENAME_TEMPLATE = "ffmpeg_log-{timestamp}.log"
CONFIG_FILE = "ffmpeg_cutter_config.json"

# --- Cleanup Tool Constants ---
CORRESPONDING_EXTENSIONS = [
    '.cutlist.txt',
    '_adjusted.vdscript',
    '_adjusted_info.txt',
    '_info.txt'
]

EXTRA_FILES = [
    'gop_info.txt',
    'VFR_info.txt'
]

SCRIPTS_LIST = [
    'vfr_detector.pyw',
    '1_Log_and_Verify.bat',
    'gop_analyzer.py',
    '2_Analyze_and_Prepare.bat',
    'vdscript_vfr_info.py',  
    'vdscript_range_adjuster.py',
    'vdscript_to_timecode_cutlist_generator.py'
]

ORIGINALS_EXT = [
    '.vdscript',
    '_frame_log.txt'
]

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

def collect_scripts(folder):
    files = []
    for name in SCRIPTS_LIST:
        f = os.path.join(folder, name)
        if os.path.exists(f):
            files.append(f)
    return files

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

# --- Configuration Management ---
def load_config():
    config_path = Path(__file__).parent / CONFIG_FILE
    if config_path.exists():
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def save_config(config):
    config_path = Path(__file__).parent / CONFIG_FILE
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=4)

# --- Main Application Class ---
class FFmpegCutterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("FFmpeg Cutter (MS Precision Edition)")

        self.start_offset_var = tk.IntVar(value=267)
        self.end_offset_var = tk.IntVar(value=1000)
        self.audio_mode_var = tk.StringVar(value="Copy")
        self.audio_bitrate_var = tk.StringVar(value="128")
        self.container_mode_var = tk.StringVar(value="Same as source")

        self.progress_var = tk.DoubleVar()
        self.time_remaining_var = tk.StringVar(value="")
        self.stop_event = threading.Event()

        self.selected_dir_var = tk.StringVar()
        self.load_last_directory()

        self.build_ui()
        self.add_top_buttons()

    def load_last_directory(self):
        config = load_config()
        last_dir = config.get("last_directory", str(Path(__file__).parent))
        if Path(last_dir).is_dir():
            self.selected_dir_var.set(last_dir)
        else:
            self.selected_dir_var.set(str(Path(__file__).parent))

    def save_last_directory(self, path):
        config = {"last_directory": path}
        save_config(config)

    def browse_directory(self):
        initial_dir = self.selected_dir_var.get() if Path(self.selected_dir_var.get()).is_dir() else str(Path(__file__).parent)
        chosen_dir = filedialog.askdirectory(initialdir=initial_dir, title="Select Folder Containing Video and Cutlist Files")
        if chosen_dir:
            self.selected_dir_var.set(chosen_dir)
            self.save_last_directory(chosen_dir)

    def build_ui(self):
        padding = {"padx": 5, "pady": 5}
        frame = ttk.Frame(self.root)
        frame.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Source Folder:").grid(row=0, column=0, sticky=tk.W, **padding)
        self.dir_entry = ttk.Entry(frame, textvariable=self.selected_dir_var, state="readonly", width=50)
        self.dir_entry.grid(row=0, column=1, columnspan=2, sticky=(tk.W, tk.E), **padding)
        
        browse_button = ttk.Button(frame, text="Browse", command=self.browse_directory)
        browse_button.grid(row=0, column=3, sticky=tk.W, **padding)

        ttk.Label(frame, text="Start Offset (ms):").grid(row=1, column=0, sticky=tk.W, **padding)
        self.start_entry = ttk.Entry(frame, textvariable=self.start_offset_var, width=6)
        self.start_entry.grid(row=1, column=1, sticky=tk.W, **padding)
        ToolTip(self.start_entry, "Seek Nudge: Pushes the seek point forward (e.g., 267 ms).")

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
            messagebox.showinfo("Completed", f"Processed {processed_segments} segments.\nLog: {log_file_path.name}")
        self.stop_event.clear()

    def add_top_buttons(self):
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(anchor="ne", padx=10, pady=5)
        
        calc_button = ttk.Button(btn_frame, text="🧮 Calculator", command=self.open_calculator)
        calc_button.pack(side="left", padx=(0,5))

        editor_button = ttk.Button(btn_frame, text="✏️ Editor", command=self.open_editor)
        editor_button.pack(side="left", padx=(0,5))

        cleanup_button = ttk.Button(btn_frame, text="🧹 Cleanup", command=self.open_cleanup)
        cleanup_button.pack(side="left", padx=(0,5))

        help_button = ttk.Button(btn_frame, text="? Help", command=self.show_help)
        help_button.pack(side="left")

    def open_calculator(self):
        calc_win = tk.Toplevel(self.root)
        calc_win.title("Frame to MS Calculator")
        calc_win.geometry("260x220")
        calc_win.transient(self.root)
        
        x = self.root.winfo_x() + 50
        y = self.root.winfo_y() + 50
        calc_win.geometry(f"+{x}+{y}")

        ttk.Label(calc_win, text="Video FPS:").pack(pady=(10,0))
        fps_entry = ttk.Entry(calc_win, width=10, justify="center")
        fps_entry.pack(pady=2)
        fps_entry.insert(0, "23.976") 

        ttk.Label(calc_win, text="Frames to Add:").pack(pady=(5,0))
        frames_entry = ttk.Entry(calc_win, width=10, justify="center")
        frames_entry.pack(pady=2)
        frames_entry.insert(0, "8") 

        result_var = tk.StringVar(value="---")
        ttk.Label(calc_win, textvariable=result_var, font=("Segoe UI", 12, "bold"), foreground="#007acc").pack(pady=10)

        def calculate():
            try:
                fps = float(fps_entry.get())
                frames = float(frames_entry.get())
                if fps <= 0: raise ValueError
                ms = (1000.0 / fps) * frames
                result_var.set(f"{int(round(ms))} ms")
            except ValueError:
                result_var.set("Error")

        ttk.Button(calc_win, text="Calculate", command=calculate).pack(pady=5)
        
        btn_frame = ttk.Frame(calc_win)
        btn_frame.pack(pady=5)

        def apply_start():
            val = result_var.get().replace(" ms", "")
            if val.isdigit():
                self.start_offset_var.set(int(val))

        def apply_end():
            val = result_var.get().replace(" ms", "")
            if val.isdigit():
                self.end_offset_var.set(int(val))

        ttk.Button(btn_frame, text="Set Start", command=apply_start, width=8).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="Set End", command=apply_end, width=8).pack(side="left", padx=2)

    def open_editor(self):
        CutlistEditorWindow(self.root, self.selected_dir_var.get())

    def open_cleanup(self):
        CleanupToolWindow(self.root, self.selected_dir_var.get())

    def show_help(self):
        msg = """FFmpeg Cutter (MS Precision Edition)
-------------------------------------------------------------
HOW TO USE:
1. Ensure your folder contains video files and corresponding .cutlist.txt files.
2. Select the folder above.
3. Adjust your Millisecond Offsets.
4. Choose Audio/Container settings and click 'Start Cutting'.

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
FRAME RATE MS CHEAT SHEET (For 8 Frames):
To calculate a specific number of frames, use the CALCULATOR 
button or the approximate values below:

FRAME RATE (FPS)      1 FRAME DURATION      8 FRAMES (Approx)
-------------------------------------------------------------
  23.976 fps   ---->    41.7 ms            334 ms
  24.000 fps   ---->    41.7 ms            333 ms
  25.000 fps   ---->    40.0 ms            320 ms
  29.970 fps   ---->    33.4 ms            267 ms
  30.000 fps   ---->    33.3 ms            267 ms
  50.000 fps   ---->    20.0 ms            160 ms
  59.940 fps   ---->    16.7 ms            133 ms
  60.000 fps   ---->    16.7 ms            133 ms

Example: 
To add an 8-frame seek nudge for a 60fps video:
8 * 16.7 = ~133 ms. Enter '133' in the Start Offset box.

-------------------------------------------------------------
Audio Modes:
- Copy: Losslessly copies the audio stream. No re-encoding. Bitrate not applicable.
- AAC / MP3: Re-encodes audio to the selected lossy format at a specified bitrate.
- WAV: Re-encodes audio to uncompressed WAV (PCM). Bitrate not applicable.
  *Note: When WAV audio is selected, the output container will automatically be set to MKV,
  as WAV is most reliably supported in the MKV container.*

Configuration:
The last selected folder is automatically saved and loaded.
Other default values can still be changed by editing this file. Look for:

    self.start_offset_var = tk.IntVar(value=267)
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

# --- NEW: Line Number Canvas Helper ---
class LineNumberCanvas(tk.Canvas):
    def __init__(self, *args, **kwargs):
        tk.Canvas.__init__(self, *args, **kwargs)
        self.textwidget = None

    def attach(self, text_widget):
        self.textwidget = text_widget

    def redraw(self, *args):
        self.delete("all")
        if not self.textwidget:
            return
        i = self.textwidget.index("@0,0")
        while True:
            dline = self.textwidget.dlineinfo(i)
            if dline is None: 
                break
            y = dline[1]
            linenum = str(i).split(".")[0]
            self.create_text(32, y, anchor="ne", text=linenum, font=("Consolas", 10), fill="#888888")
            i = self.textwidget.index(f"{i}+1line")

# --- Cutlist Editor Window Class ---
class CutlistEditorWindow:
    def __init__(self, master, default_dir):
        self.window = tk.Toplevel(master)
        self.window.title("FFmpeg Cutter - Cutlist Editor")
        self.window.geometry("750x550")
        self.window.transient(master)

        self.current_file_path = None
        self.default_dir = default_dir

        self.build_ui()

    def build_ui(self):
        top_frame = ttk.Frame(self.window)
        top_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(top_frame, text="Load Cutlist", command=self.load_file).pack(side=tk.LEFT, padx=5)
        ttk.Button(top_frame, text="Save Changes", command=self.save_file).pack(side=tk.LEFT, padx=5)
        
        self.file_label = ttk.Label(top_frame, text="No file loaded.", foreground="gray")
        self.file_label.pack(side=tk.LEFT, padx=15)

        paned = ttk.PanedWindow(self.window, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        text_frame = ttk.Frame(paned)
        paned.add(text_frame, weight=3)
        
        self.line_numbers = LineNumberCanvas(text_frame, width=38, background="#f0f0f0", highlightthickness=0)
        self.line_numbers.pack(side=tk.LEFT, fill=tk.Y)

        self.text_area = tk.Text(text_frame, wrap="none", font=("Consolas", 10), undo=True)
        self.text_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar_y = ttk.Scrollbar(text_frame, command=self.text_area.yview)
        scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)

        self.line_numbers.attach(self.text_area)

        def _on_scroll(*args):
            scrollbar_y.set(*args)
            self.line_numbers.redraw()

        self.text_area.configure(yscrollcommand=_on_scroll)
        self.text_area.bind("<KeyRelease>", lambda e: self.line_numbers.redraw())
        self.text_area.bind("<MouseWheel>", lambda e: self.window.after(10, self.line_numbers.redraw))
        self.text_area.bind("<Configure>", lambda e: self.line_numbers.redraw())

        tools_frame = ttk.LabelFrame(paned, text="Editor Tools", padding=10)
        paned.add(tools_frame, weight=1)

        lbl1 = ttk.Label(tools_frame, text="1. Expand Start Earlier", font=("Segoe UI", 9, "bold"))
        lbl1.pack(anchor="w", pady=(0, 5))

        f1 = ttk.Frame(tools_frame)
        f1.pack(fill=tk.X, pady=2)
        ttk.Label(f1, text="Line #:").pack(side=tk.LEFT)
        self.seg_entry = ttk.Entry(f1, width=5)
        self.seg_entry.pack(side=tk.RIGHT)

        f2 = ttk.Frame(tools_frame)
        f2.pack(fill=tk.X, pady=2)
        ttk.Label(f2, text="Seconds (e.g. 1.0):").pack(side=tk.LEFT)
        self.shift_entry = ttk.Entry(f2, width=5)
        self.shift_entry.pack(side=tk.RIGHT)

        ttk.Button(tools_frame, text="Apply Expansion", command=self.apply_shift).pack(fill=tk.X, pady=(5, 15))

        lbl2 = ttk.Label(tools_frame, text="2. Bridge Gap", font=("Segoe UI", 9, "bold"))
        lbl2.pack(anchor="w", pady=(0, 5))

        f3 = ttk.Frame(tools_frame)
        f3.pack(fill=tk.X, pady=2)
        ttk.Label(f3, text="From Line #:").pack(side=tk.LEFT)
        self.bridge_start_entry = ttk.Entry(f3, width=5)
        self.bridge_start_entry.pack(side=tk.RIGHT)

        f4 = ttk.Frame(tools_frame)
        f4.pack(fill=tk.X, pady=2)
        ttk.Label(f4, text="To Line #:").pack(side=tk.LEFT)
        self.bridge_end_entry = ttk.Entry(f4, width=5)
        self.bridge_end_entry.pack(side=tk.RIGHT)

        ttk.Button(tools_frame, text="Apply Bridge", command=self.apply_bridge).pack(fill=tk.X, pady=(5, 15))

    def load_file(self):
        file_path = filedialog.askopenfilename(
            initialdir=self.default_dir,
            title="Select Cutlist",
            filetypes=(("Cutlist Files", "*.cutlist.txt"), ("All Files", "*.*"))
        )
        if file_path:
            self.current_file_path = file_path
            self.file_label.config(text=Path(file_path).name, foreground="black")
            with open(file_path, "r") as f:
                content = f.read()
            self.text_area.delete(1.0, tk.END)
            self.text_area.insert(tk.END, content)
            self.window.after(50, self.line_numbers.redraw)

    def save_file(self):
        if not self.current_file_path:
            messagebox.showwarning("Warning", "No file loaded.", parent=self.window)
            return
        try:
            content = self.text_area.get(1.0, tk.END)
            if content.endswith("\n"): content = content[:-1]
            with open(self.current_file_path, "w") as f: f.write(content)
            messagebox.showinfo("Success", "File saved successfully.", parent=self.window)
        except Exception as e:
            messagebox.showerror("Error", f"Could not save file:\n{e}", parent=self.window)

    def get_segments_data(self):
        lines = self.text_area.get(1.0, tk.END).splitlines()
        pattern = re.compile(r'start_time=([\d.]+),duration=([\d.]+)')
        segments = {}
        for i, line in enumerate(lines):
            match = pattern.search(line)
            if match:
                segments[i + 1] = {
                    'line_idx': i,
                    'start': float(match.group(1)),
                    'duration': float(match.group(2))
                }
        return lines, segments

    def update_text_area(self, lines):
        self.text_area.delete(1.0, tk.END)
        self.text_area.insert(tk.END, "\n".join(lines))
        self.line_numbers.redraw()

    def apply_shift(self):
        try:
            line_num = int(self.seg_entry.get())
            shift_sec = float(self.shift_entry.get())
        except ValueError:
            messagebox.showerror("Error", "Please enter valid numbers.", parent=self.window)
            return
        lines, segments = self.get_segments_data()
        if line_num not in segments:
            messagebox.showerror("Error", f"No segment on line {line_num}.", parent=self.window)
            return
        target = segments[line_num]
        new_start = max(0.0, target['start'] - shift_sec)
        adj_shift = target['start'] - new_start
        new_dur = target['duration'] + adj_shift
        lines[target['line_idx']] = f"start_time={new_start:.6f},duration={new_dur:.6f}"
        self.update_text_area(lines)
        messagebox.showinfo("Success", f"Added {adj_shift:.3f}s to the start of the segment on line {line_num}.", parent=self.window)

    def apply_bridge(self):
        try:
            start_num = int(self.bridge_start_entry.get())
            end_num = int(self.bridge_end_entry.get())
        except ValueError:
            messagebox.showerror("Error", "Please enter valid line numbers.", parent=self.window)
            return
        lines, segments = self.get_segments_data()
        if start_num >= end_num or start_num not in segments or end_num not in segments:
            messagebox.showerror("Error", "Invalid line range.", parent=self.window)
            return
        start_seg, end_seg = segments[start_num], segments[end_num]
        bridge_end_time = end_seg['start'] + end_seg['duration']
        new_dur = bridge_end_time - start_seg['start']
        lines[start_seg['line_idx']] = f"start_time={start_seg['start']:.6f},duration={new_dur:.6f}"
        for i in range(start_seg['line_idx'] + 1, end_seg['line_idx'] + 1):
            lines[i] = "" 
        self.update_text_area(lines)
        messagebox.showinfo("Success", f"Bridged from line {start_num} to {end_num}.", parent=self.window)

# --- Cleanup Tool Window Class ---
class CleanupToolWindow:
    def __init__(self, master, default_dir):
        self.window = tk.Toplevel(master)
        self.window.title("Cleanup Tool")
        self.window.geometry("500x320")
        self.window.transient(master)

        self.folder = tk.StringVar(value=default_dir)
        self.remove_scripts = tk.BooleanVar()
        self.remove_output_segments = tk.BooleanVar()
        self.remove_originals = tk.BooleanVar()

        self.build_ui()

    def build_ui(self):
        padding = {"padx": 15, "pady": 5}
        ttk.Label(self.window, text="Select folder to clean:").pack(anchor="w", **padding)
        frame = ttk.Frame(self.window)
        frame.pack(fill="x", padx=15)
        ttk.Entry(frame, textvariable=self.folder, width=50).pack(side="left", expand=1, fill="x")
        ttk.Button(frame, text="Browse", command=self.browse_folder).pack(side="right", padx=(5,0))

        chk_frame = ttk.Frame(self.window)
        chk_frame.pack(fill="both", expand=True, padx=15, pady=10)
        ttk.Checkbutton(chk_frame, text="Remove scripts", variable=self.remove_scripts).pack(anchor="w", pady=2)
        ttk.Checkbutton(chk_frame, text="Remove output segments", variable=self.remove_output_segments).pack(anchor="w", pady=2)
        tk.Checkbutton(chk_frame, text="Remove original vdscripts & frame logs - CAUTION", variable=self.remove_originals, fg="darkred").pack(anchor="w", pady=(10, 2))

        btn_frame = ttk.Frame(self.window)
        btn_frame.pack(fill="x", padx=15, pady=10)
        ttk.Button(btn_frame, text="Run Cleanup", command=self.cleanup).pack(side="left")
        ttk.Button(btn_frame, text="Help", command=self.show_help).pack(side="right")

    def browse_folder(self):
        folder = filedialog.askdirectory(initialdir=self.folder.get())
        if folder: self.folder.set(folder)

    def cleanup(self):
        folder = self.folder.get()
        if not folder or not os.path.isdir(folder): return
        video_files = get_video_files(folder)
        files_to_move = collect_corresponding_files(folder, video_files)
        if self.remove_scripts.get(): files_to_move += collect_scripts(folder)
        
        folders_to_move = []
        if self.remove_output_segments.get():
            segs = collect_output_segment_folders(folder, video_files)
            if segs and messagebox.askyesno("Warning", "Move segments to delete folder?", parent=self.window):
                folders_to_move += segs
        
        if self.remove_originals.get():
            origs = collect_originals(folder, video_files)
            if origs and messagebox.askyesno("Warning", "Move originals? Recreating them can take a long time!", parent=self.window):
                files_to_move += origs

        if files_to_move: move_files(folder, files_to_move)
        if folders_to_move: move_folders(folder, folders_to_move)
        messagebox.showinfo("Cleanup", "Done.", parent=self.window)

    def show_help(self):
        help_text = (
            "Cleanup Tool — Help\n\n"
            "This tool helps you declutter folders containing video projects created using the VffEdit workflow.\n\n"
            "Default behaviour (no boxes checked):\n"
            "- Moves temporary/output files that sit next to your video files into a 'delete' subfolder.\n"
            "- These include files like .cutlist.txt, *_adjusted.vdscript, *_adjusted_info.txt, *_info.txt.\n"
            "- Also moves gop_info.txt, VFR_info.txt, and all .log files found in the folder.\n"
            "- Original video files (.mp4, .mkv, .mov, etc.) are NEVER moved.\n\n"
            "\"Remove scripts\" checkbox:\n"
            "- If checked, moves the helper/automation scripts  into the 'delete' folder.\n"
            "- Example: vfr_detector.pyw, 1_Log_and_Verify.bat, vdscript_vfr_info.py, vdscript_range_adjuster.py, etc.\n\n"
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
        # Create a scrollable help window
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
    root = tk.Tk()
    app = FFmpegCutterApp(root)
    root.mainloop()