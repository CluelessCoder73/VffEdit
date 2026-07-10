# VffEdit (Formerly ExactCut Video Tools)

Welcome to **VffEdit**, the centralized graphical orchestrator for your video editing and frame-accurate cutting pipeline. 

VffEdit replaces scattered batch files and manual directory management with a single, unified interface (`vffedit.pyw`) that manages project states, executes background Python scripts, and pipes real-time outputs straight to an integrated console log.

---

## 📁 Directory Structure

For the orchestrator to route processes correctly, maintain the following directory layout:

```text
VffEdit/
│
├── vffedit.pyw                  # The Master GUI Application (Run this!)
│
└── scripts/                     # Core backend processing suite
    ├── vdscript_range_adjuster.py
    ├── gop_analyzer.py
    ├── vdscript_vfr_info.py
    ├── vdscript_to_timecode_cutlist_generator.py
    ├── vdscript_to_cpf.py
    ├── vfr_detector.pyw
    └── ffmpeg_cutter.pyw

```

---

## 🚀 The VffEdit Workflow

### 1. Project Initialization & Verification

* **Select Project Folder:** Point VffEdit to the folder containing your raw source videos.
* **Step 1: Extract Frame Logs:** Automatically runs background FFmpeg tasks to generate essential `_frame_log.txt` files for every video detected.
* **Step 2: Check VFR Health:** Launches the VFR Detector utility to analyze variable frame rate edge-cases.

### 2. The VirtualDub2 Editing Phase

Click the **VirtualDub2 Info** button in the GUI for a quick reminder of the edit export steps:

1. Open your video (or proxy) in VirtualDub2 and make your cuts.
2. Navigate to `File > Save processing settings...` (`Ctrl + S`).
3. Ensure **"Include selection and edit list"** is checked.
4. Save the file in your project folder matching the exact pattern: `[VideoName].[Extension].vdscript` (e.g., `vacation.mp4.vdscript`).

### 3. Analysis & Adjustment

* **Adjust Parameters:** Fine-tune your **I-Frame Offset** and **Minimum Gap (frames)** dynamically from the GUI settings panel.
* **Step 3: Analyze & Adjust Cutlists:** Fires off the sequential script pipeline:
* Adjusts the original `.vdscript` cuts based on your offset/gap math.
* Runs the GOP Analyzer to map keyframes (`gop_info.txt`).
* Generates VFR-aware informational logs.
* Outputs the finalized `.cutlist.txt` files.



### 4. Lossless Cutting

* **Step 4: Launch FFmpeg Cutter:** Opens the standalone `ffmpeg_cutter.pyw` GUI utility to losslessly slice your videos using your newly tailored cutlists.

### 5. Merge

Open LosslessCut, go to Tools > Merge/concatenate files, browse for desired folder, select all the parts, then merge. Repeat this process until all the parts in each subfolder have been merged - & that's it - FINITO!
* **Cleanup:** Use the **🧹 Cleanup** button inside the FFmpeg Cutter to automatically sweep all the leftover files (cutlists, log files etc) into a `delete` folder to keep your workspace tidy.

---

## ⚙️ Requirements

* **Python 3.x**
* **LosslessCut
* **FFmpeg** (Standalone or via LosslessCut)
* **VirtualDub2** (build 44282 or similar)
* **HandBrake** (For proxy generation)

---
