import os
import sys
import subprocess
import threading
import tkinter as tk
import re
from tkinter import ttk, filedialog, scrolledtext, messagebox
from pathlib import Path

# VffEdit Master Orchestrator

class VffEditApp:
    def __init__(self, root):
        self.root = root
        self.root.title("VffEdit (ExactCut Orchestrator)")
        self.root.geometry("1100x750")
        
        self.target_folder = tk.StringVar(value="No folder selected")
        self.i_frame_offset_var = tk.IntVar(value=1)
        self.min_gap_var = tk.IntVar(value=150)
        self.enable_cpf_var = tk.BooleanVar(value=False)
        self.full_gop_var = tk.BooleanVar(value=False)
        
        self.scripts_dir = Path(__file__).parent / "scripts"
        
        self.build_ui()

    def build_ui(self):
        # --- TOP PANEL: Folder Selection ---
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(fill=tk.X)
        
        ttk.Label(top_frame, text="Project Folder:", font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        ttk.Entry(top_frame, textvariable=self.target_folder, state="readonly", width=60).pack(side=tk.LEFT, padx=10)
        ttk.Button(top_frame, text="Browse...", command=self.browse_folder).pack(side=tk.LEFT)
        ttk.Button(top_frame, text="Refresh Status", command=self.update_status).pack(side=tk.LEFT, padx=10)

        # --- MAIN SPLIT ---
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # --- LEFT PANEL: Workflow & Settings ---
        left_frame = ttk.Frame(paned, width=320)
        paned.add(left_frame, weight=0)
        
        # Settings
        settings_group = ttk.LabelFrame(left_frame, text="Settings", padding=10)
        settings_group.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(settings_group, text="I-Frame Offset:").grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Spinbox(settings_group, from_=0, to=5, textvariable=self.i_frame_offset_var, width=5).grid(row=0, column=1, sticky=tk.W)
        
        ttk.Label(settings_group, text="Min Gap (frames):").grid(row=1, column=0, sticky=tk.W, pady=2)
        ttk.Entry(settings_group, textvariable=self.min_gap_var, width=8).grid(row=1, column=1, sticky=tk.W)
        
        ttk.Checkbutton(settings_group, text="Full GOP Mode (Disable Short Cut)", variable=self.full_gop_var).grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(5,0))
        ttk.Checkbutton(settings_group, text="Enable CPF Export (Cuttermaran)", variable=self.enable_cpf_var).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=2)

        # Workflow Buttons
        workflow_group = ttk.LabelFrame(left_frame, text="Workflow Pipeline", padding=10)
        workflow_group.pack(fill=tk.BOTH, expand=True)
        
        btn_opts = {"fill": tk.X, "pady": 5, "ipady": 5}
        
        ttk.Button(workflow_group, text="Step 1: Extract Frame Logs", command=self.run_step_1).pack(**btn_opts)
        ttk.Button(workflow_group, text="Step 2: Check VFR Health", command=self.run_vfr_detector).pack(**btn_opts)
        
        ttk.Separator(workflow_group, orient='horizontal').pack(fill=tk.X, pady=10)
        
        ttk.Button(workflow_group, text="Edit Phase: VirtualDub2 Info", command=self.show_vd2_info).pack(**btn_opts)
        
        ttk.Separator(workflow_group, orient='horizontal').pack(fill=tk.X, pady=10)
        
        ttk.Button(workflow_group, text="Step 3: Analyze & Adjust Cutlists", command=self.run_step_3).pack(**btn_opts)
        ttk.Button(workflow_group, text="Step 4: Launch FFmpeg Cutter", command=self.run_step_4).pack(**btn_opts)

        # --- RIGHT PANEL: Notebook Tabs ---
        self.notebook = ttk.Notebook(paned)
        paned.add(self.notebook, weight=1)
        
        # TAB 1: Console & Status
        tab1 = ttk.Frame(self.notebook)
        self.notebook.add(tab1, text="Console & Status")
        
        status_group = ttk.LabelFrame(tab1, text="Project Status", padding=10)
        status_group.pack(fill=tk.X, padx=5, pady=5)
        
        self.status_text = tk.Text(status_group, height=4, font=("Consolas", 9), bg="#f0f0f0", relief="flat")
        self.status_text.pack(fill=tk.BOTH)
        
        console_group = ttk.LabelFrame(tab1, text="Console Output", padding=10)
        console_group.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.console = scrolledtext.ScrolledText(console_group, font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4")
        self.console.pack(fill=tk.BOTH, expand=True)

        # TAB 2: Cutlist Comparison
        tab2 = ttk.Frame(self.notebook)
        self.notebook.add(tab2, text="Cutlist Comparison")
        
        comp_top = ttk.Frame(tab2, padding=10)
        comp_top.pack(fill=tk.X)
        
        ttk.Label(comp_top, text="Select Cutlist:").pack(side=tk.LEFT, padx=(0, 5))
        self.compare_combo = ttk.Combobox(comp_top, state="readonly", width=40)
        self.compare_combo.pack(side=tk.LEFT)
        self.compare_combo.bind("<<ComboboxSelected>>", self.on_compare_select)
        
        compare_split = ttk.PanedWindow(tab2, orient=tk.HORIZONTAL)
        compare_split.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        orig_frame = ttk.LabelFrame(compare_split, text="Original Info")
        compare_split.add(orig_frame, weight=1)
        self.comp_orig_text = scrolledtext.ScrolledText(orig_frame, font=("Consolas", 9), wrap="none")
        self.comp_orig_text.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        
        adj_frame = ttk.LabelFrame(compare_split, text="Adjusted Info (Aligned)")
        compare_split.add(adj_frame, weight=1)
        self.comp_adj_text = scrolledtext.ScrolledText(adj_frame, font=("Consolas", 9), wrap="none")
        self.comp_adj_text.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        self.log("VffEdit Initialized. Please select a project folder.")

    # --- UI Helpers ---
    def log(self, message):
        self.console.insert(tk.END, message + "\n")
        self.console.see(tk.END)

    def browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.target_folder.set(folder)
            self.update_status()

    def update_status(self):
        folder = self.target_folder.get()
        if not os.path.isdir(folder):
            return
            
        p = Path(folder)
        videos = [f for f in p.iterdir() if f.suffix.lower() in ['.mp4', '.m4v', '.mkv', '.mov', '.avi', '.mpv', '.m1v', '.m2v']]
        logs = list(p.glob("*_frame_log.txt"))
        vdscripts = list(p.glob("*.vdscript"))
        adjusted = list(p.glob("*_adjusted.vdscript"))
        
        self.status_text.config(state="normal")
        self.status_text.delete(1.0, tk.END)
        self.status_text.insert(tk.END, f"Found {len(videos)} Video Files\n")
        self.status_text.insert(tk.END, f"Found {len(logs)} Frame Logs\n")
        self.status_text.insert(tk.END, f"Found {len(vdscripts)} VDScripts\n")
        self.status_text.insert(tk.END, f"Found {len(adjusted)} Adjusted Cutlists\n")
        self.status_text.config(state="disabled")
        
        # Update dropdown for comparison tab
        info_files = [f.name for f in p.glob("*_info.txt") if not f.name.endswith("_adjusted_info.txt") and f.name != "gop_info.txt"]
        self.compare_combo['values'] = info_files
        if info_files:
            if not self.compare_combo.get() in info_files:
                self.compare_combo.set(info_files[0])
            self.on_compare_select(None)
        else:
            self.compare_combo.set('')
            self.comp_orig_text.delete(1.0, tk.END)
            self.comp_adj_text.delete(1.0, tk.END)

    def show_vd2_info(self):
        msg = (
            "VirtualDub2 Editing Phase\n\n"
            "1. Open your video (or proxy) in VirtualDub2.\n"
            "2. Make your cuts freely.\n"
            "3. Go to File > Save processing settings... (CTRL + S)\n"
            "4. Ensure 'Include selection and edit list' is CHECKED.\n"
            "5. Save in your project folder as exactly: [VideoName].[Ext].vdscript\n"
            "   (Example: vacation.mp4.vdscript)"
        )
        messagebox.showinfo("VirtualDub2 Instructions", msg)

    # --- Compare Alignment Logic ---
    def on_compare_select(self, event):
        folder = self.target_folder.get()
        orig_file = self.compare_combo.get()
        if not folder or not orig_file: return
        
        orig_path = Path(folder) / orig_file
        # Construct adjusted filename (e.g., vacation.mp4_info.txt -> vacation.mp4_adjusted_info.txt)
        adj_name = orig_file.replace("_info.txt", "_adjusted_info.txt")
        adj_path = Path(folder) / adj_name
        
        if not orig_path.exists(): return
        with open(orig_path, 'r', encoding='utf-8') as f:
            orig_content = f.read()
            
        self.comp_orig_text.delete(1.0, tk.END)
        self.comp_orig_text.insert(tk.END, orig_content)
        self.comp_adj_text.delete(1.0, tk.END)
        
        if not adj_path.exists():
            self.comp_adj_text.insert(tk.END, "[Adjusted file not generated yet. Run Step 3.]")
            return
            
        with open(adj_path, 'r', encoding='utf-8') as f:
            adj_content = f.read()
            
        # The Alignment Algorithm
        range_pattern = re.compile(r"\(Frames (\d+)\s*-\s*(\d+)\)")
        orig_ranges = []
        for line in orig_content.splitlines():
            match = range_pattern.search(line)
            if match:
                orig_ranges.append((int(match.group(1)), int(match.group(2))))
                
        adj_display = []
        orig_idx = 0
        
        for line in adj_content.splitlines():
            match = range_pattern.search(line)
            if match:
                adj_start, adj_end = int(match.group(1)), int(match.group(2))
                covered = 0
                while orig_idx < len(orig_ranges):
                    o_start, o_end = orig_ranges[orig_idx]
                    # Check if original cut falls within the adjusted boundary
                    if adj_start <= o_start <= adj_end:
                        covered += 1
                        orig_idx += 1
                    else:
                        break
                        
                adj_display.append(line)
                # Pad blank lines for swallowed ranges
                if covered > 1:
                    for _ in range(covered - 1):
                        adj_display.append("")
            else:
                adj_display.append(line)
                
        self.comp_adj_text.insert(tk.END, "\n".join(adj_display))

    # --- Workflow Steps ---
    def run_step_1(self):
        folder = self.target_folder.get()
        if not os.path.isdir(folder):
            messagebox.showerror("Error", "Select a folder first.")
            return

        def extract_logs():
            self.log("\n--- Starting Frame Log Extraction ---")
            p = Path(folder)
            videos = [f for f in p.iterdir() if f.suffix.lower() in ['.mp4', '.m4v', '.mkv', '.mov', '.avi', '.mpv', '.m1v', '.m2v']]
            
            for vid in videos:
                log_path = p / f"{vid.name}_frame_log.txt"
                if log_path.exists():
                    self.log(f"[Skipping] Log already exists: {log_path.name}")
                    continue
                
                self.log(f"Processing: {vid.name} (This may take a moment...)")
                cmd = f'ffmpeg -i "{vid}" -vf showinfo -f null -'
                
                try:
                    process = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True, shell=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                    with open(log_path, 'w', encoding='utf-8') as log_file:
                        for line in process.stderr:
                            if "n:" in line.lower():
                                log_file.write(line)
                    self.log(f"[OK] Finished: {vid.name}")
                except Exception as e:
                    self.log(f"Error processing {vid.name}: {e}")
            
            self.log("--- Frame Log Extraction Complete ---")
            self.root.after(0, self.update_status)

        threading.Thread(target=extract_logs, daemon=True).start()

    def run_vfr_detector(self):
        folder = self.target_folder.get()
        if not os.path.isdir(folder): return
        script_path = self.scripts_dir / "exactcut_vfr_detector.pyw"
        subprocess.Popen([sys.executable, str(script_path)], cwd=folder)
        self.log("\nLaunched VFR Detector.")

    def check_gop_warning(self):
        folder = Path(self.target_folder.get())
        gop_file = folder / "gop_info.txt"
        if not gop_file.exists(): return
        
        try:
            with open(gop_file, 'r', encoding='utf-8') as f:
                content = f.read()
            match = re.search(r"Smallest starting GOP in all vdscripts:\s*(\d+)", content)
            if match:
                smallest_gop = int(match.group(1))
                if smallest_gop <= 8:
                    msg = (f"⚠️ GOP WARNING ⚠️\n\n"
                           f"The Smallest starting GOP was detected as: {smallest_gop} frames.\n\n"
                           f"Because this is 8 frames or less, your Seek Nudge might jump over a keyframe and lose footage.\n\n"
                           f"Please check the Help section in `gop_analyzer.py` or use the 'Editor' tool (found in the FFmpeg Cutter) to bridge the gap or push the cut backward!")
                    messagebox.showwarning("GOP Safety Warning", msg)
        except Exception as e:
            self.log(f"Failed to check GOP warning: {e}")

    def run_step_3(self):
        folder = self.target_folder.get()
        if not os.path.isdir(folder): return
        
        def sequential_worker():
            self.log("\n=== Starting Step 3: Analysis Pipeline ===")
            
            # Setup Adjuster Command with conditional Full GOP flag
            adj_cmd = [sys.executable, str(self.scripts_dir / "vdscript_range_adjuster.py"), "--dir", folder, "--offset", str(self.i_frame_offset_var.get()), "--mingap", str(self.min_gap_var.get())]
            if self.full_gop_var.get():
                adj_cmd.append("--fullgop")

            cmds = [
                (adj_cmd, "Range Adjuster"),
                ([sys.executable, str(self.scripts_dir / "gop_analyzer.py")], "GOP Analyzer"),
                ([sys.executable, str(self.scripts_dir / "vdscript_vfr_info.py")], "VFR Info Generator"),
                ([sys.executable, str(self.scripts_dir / "vdscript_to_timecode_cutlist_generator.py")], "Cutlist Generator")
            ]
            
            if self.enable_cpf_var.get():
                cmds.append(([sys.executable, str(self.scripts_dir / "vdscript_to_cpf.py")], "CPF Generator"))

            for cmd, name in cmds:
                self.log(f"\n--- Running: {name} ---")
                try:
                    proc = subprocess.run(cmd, cwd=folder, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                    if proc.stdout: self.log(proc.stdout)
                    if proc.stderr: self.log(proc.stderr)
                except Exception as e:
                    self.log(f"Error running {name}: {e}")
            
            self.log("=== Step 3 Complete ===")
            
            # Schedule UI updates back on the main thread safely
            self.root.after(0, self.update_status)
            self.root.after(500, self.check_gop_warning)

        threading.Thread(target=sequential_worker, daemon=True).start()

    def run_step_4(self):
        script_path = self.scripts_dir / "exactcut_ffmpeg_cutter.pyw"
        if not script_path.exists():
            self.log("Error: Cutter script not found.")
            return
            
        subprocess.Popen([sys.executable, str(script_path)])
        self.log("\nLaunched ExactCut FFmpeg Cutter.")

if __name__ == "__main__":
    root = tk.Tk()
    app = VffEditApp(root)
    root.mainloop()