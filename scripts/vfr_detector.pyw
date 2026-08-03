r"""
VFR Detector (vfr_detector.pyw)

This script scans FFmpeg *_frame_log.txt files for Variable Frame Rate (VFR), 
using forgiving parameters to reduce false positives.
"""
import os
import re
import sys
import threading
import tkinter as tk
from tkinter import scrolledtext, messagebox

def vfr_detector_forgiving(
    log_file_path,
    ignore_initial_frames,
    ignore_zero_duration,
    duration_tolerance,
    suspicious_threshold=20
):
    """
    Scans a single _frame_log.txt file to detect VFR.
    Groups similar durations based on the tolerance (Default 1ms).
    """
    unique_grouped_durations = []
    log_pattern = re.compile(r"n:(\d+)\s+.*?duration_time:([0-9.]+)")

    try:
        with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                match = log_pattern.search(line)
                if match:
                    frame_number = int(match.group(1))
                    duration_time = float(match.group(2))

                    if frame_number < ignore_initial_frames:
                        continue
                    if ignore_zero_duration and duration_time == 0.0:
                        continue

                    found_group = False
                    for i, existing_avg_duration in enumerate(unique_grouped_durations):
                        if abs(duration_time - existing_avg_duration) < duration_tolerance:
                            found_group = True
                            break
                    
                    if not found_group:
                        unique_grouped_durations.append(duration_time)

    except Exception:
        return "ERROR", []

    unique_count = len(unique_grouped_durations)
    if unique_count <= 1:
        status = "CFR"
    elif unique_count <= suspicious_threshold:
        status = "VFR_HEALTHY"
    else:
        status = "VFR_SUSPICIOUS"

    return status, unique_grouped_durations

def generate_summary_text(vfr_detected, suspicious_detected):
    """Creates a clear, encouraging summary for the user."""
    lines = ["\n" + "="*45 + "\n"]
    lines.append(" FINAL SUMMARY & RECOMMENDATION\n")
    lines.append("="*45 + "\n")
    
    if suspicious_detected:
        lines.append("⚠️  ALERT: SUSPICIOUS TIMESTAMPS DETECTED!\n")
        lines.append("One or more videos exhibit extreme frame duration jitter (>20 unique durations).\n")
        lines.append("\nACTION REQUIRED:\n")
        lines.append("- First, try increasing 'Duration Tolerance' to 0.002 in the GUI.\n")
        lines.append("- If it remains suspicious, remux the file with FFmpeg:\n")
        lines.append("  ffmpeg -i input.mp4 -c copy -video_track_timescale 90k fixed.mp4\n")
    elif vfr_detected:
        lines.append("✅  STATUS: VFR DETECTED (HEALTHY)\n")
        lines.append("\nCONFIRMATION: Your videos are healthy and safe to process.\n")
        lines.append("VffEdit's millisecond precision will handle this perfectly.\n")
        lines.append(">>> IT IS SAFE TO PROCEED WITH YOUR PROJECT. <<<\n")
    else:
        lines.append("✅  STATUS: CFR DETECTED (CONSTANT)\n")
        lines.append("\nCONFIRMATION: No variable frame rate issues found.\n")
        lines.append(">>> IT IS SAFE TO PROCEED WITH YOUR PROJECT. <<<\n")
    
    return "".join(lines)

class VFRDetectorApp:
    def __init__(self, master, target_folder):
        self.master = master
        master.title("VFR Detector")
        master.geometry("800x750")
        master.configure(bg="#2c3e50")

        self.current_folder = target_folder

        # --- Parameters ---
        self.params_frame = tk.LabelFrame(master, text="Detection Parameters", padx=15, pady=15, bg="#34495e", fg="white")
        self.params_frame.pack(pady=15, padx=20, fill="x")

        tk.Label(self.params_frame, text="Ignore First N Frames:", bg="#34495e", fg="white").grid(row=0, column=0, sticky="w")
        self.initial_frames_var = tk.IntVar(value=50)
        tk.Spinbox(self.params_frame, from_=0, to_=1000, textvariable=self.initial_frames_var, width=8).grid(row=0, column=1, sticky="w", padx=10)

        tk.Label(self.params_frame, text="Duration Tolerance (sec):", bg="#34495e", fg="white").grid(row=1, column=0, sticky="w")
        self.duration_tolerance_var = tk.DoubleVar(value=0.001) 
        tk.Entry(self.params_frame, textvariable=self.duration_tolerance_var, width=12).grid(row=1, column=1, sticky="w", padx=10)

        # --- Actions ---
        folder_display = self.current_folder if self.current_folder else "No folder provided (Run via VffEdit Master Orchestrator)"
        self.folder_path_var = tk.StringVar(value=folder_display)
        tk.Label(master, textvariable=self.folder_path_var, bg="#ecf0f1", pady=8, relief="sunken").pack(fill="x", padx=20)
        
        btn_frame = tk.Frame(master, bg="#2c3e50")
        btn_frame.pack(pady=10)
        
        tk.Button(btn_frame, text="Rerun Detection", command=self.start_thread, bg="#3498db", fg="white", padx=15, pady=5).pack(side="left", padx=5)

        self.output_text = scrolledtext.ScrolledText(master, bg="#ecf0f1", fg="#2c3e50", font=("Consolas", 10), padx=10, pady=10)
        self.output_text.pack(pady=15, padx=20, fill="both", expand=True)

        # Automatically start the scan if a valid folder was passed by VffEdit
        if self.current_folder and os.path.isdir(self.current_folder):
            self.master.after(500, self.start_thread)

    def start_thread(self):
        if not self.current_folder or not os.path.isdir(self.current_folder): 
            messagebox.showwarning("Warning", "No valid project folder detected. Please run this through VffEdit!")
            return
        self.output_text.delete(1.0, tk.END)
        self.output_text.insert(tk.END, "Scanning logs... Please wait.\n\n")
        threading.Thread(target=self.run_logic, daemon=True).start()

    def run_logic(self):
        log_files = [f for f in os.listdir(self.current_folder) if f.endswith('_frame_log.txt')]
        vfr_detected = False
        suspicious_detected = False
        results = []

        if not log_files:
            results.append("No _frame_log.txt files found in this directory.")
        else:
            for log_file in log_files:
                status, durations = vfr_detector_forgiving(os.path.join(self.current_folder, log_file), 
                                                            self.initial_frames_var.get(), True, self.duration_tolerance_var.get())
                results.append(f"FILE: {log_file}\nRESULT: {status} ({len(durations)} groups)\n")
                results.append("-" * 40 + "\n")
                if status == "VFR_SUSPICIOUS": suspicious_detected = True
                elif status == "VFR_HEALTHY": vfr_detected = True

        final_gui_text = "".join(results) + generate_summary_text(vfr_detected, suspicious_detected)
        
        # Clear the "Scanning..." message and output results
        self.master.after(0, lambda: self.output_text.delete(1.0, tk.END))
        self.master.after(0, lambda: self.output_text.insert(tk.END, final_gui_text))

if __name__ == "__main__":
    # Ingest the folder path passed from vffedit.pyw
    target = sys.argv[1] if len(sys.argv) > 1 else ""
    
    root = tk.Tk()
    VFRDetectorApp(root, target)
    root.mainloop()