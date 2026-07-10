import os
import re
import sys
from pathlib import Path

# ----------------------------------------------------------------------
# Script: vdscript_vfr_info.py
# Description:
# This script reads VirtualDub .vdscript files AND their corresponding
# FFmpeg frame logs to generate a text file containing precise, 
# timestamp-based info for every cut.
#
# Frame-log based timing:
# Reads exact timestamps from FFmpeg frame logs.
# Works with both CFR and VFR sources.
#
# Usage:
# 1. Place this script in the folder with your .vdscript and _frame_log.txt files.
# 2. Run the script.
# 3. It will auto-detect the logs and generate _info.txt files.
#
# Example:
# VirtualDub.subset.AddRange(446,444);
# VirtualDub.subset.AddRange(1397,194);
#
# Will be translated to this format in the _info.txt file:
# 00:00:18.601 - 00:00:37.120 (Frames 446 - 889)      Length: 00:00:18.518 (444 frames)
# 00:00:58.266 - 00:01:06.358 (Frames 1397 - 1590)    Length: 00:00:08.091 (194 frames)
# --------------------------------------------------------------------------------
# Total Length: 00:00:26.609 (638 frames)
# Timestamps calculated from FFmpeg frame log
#
# ----------------------------------------------------------------------

def parse_showinfo_log(log_path):
    """
    Parses a showinfo log file to extract frame numbers and pts_time.
    Returns:
        - frame_to_pts: Dictionary {frame_number: timestamp}
        - sorted_frames: List of frames (for calculating end-of-video durations)
    """
    frame_to_pts = {}
    frame_pattern = re.compile(r'n:\s*(\d+).*?pts_time:([\d.]+)')

    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                match = frame_pattern.search(line)
                if match:
                    frame_num = int(match.group(1))
                    pts_time = float(match.group(2))
                    frame_to_pts[frame_num] = pts_time
    except Exception as e:
        print(f"Error parsing log '{log_path}': {e}")
        return None, None
    
    if not frame_to_pts:
        return {}, []

    return frame_to_pts, sorted(frame_to_pts.keys())

def seconds_to_hms(seconds):
    """
    Formats seconds (float) into HH:MM:SS.mmm string.
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    milliseconds = int((seconds % 1) * 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}.{milliseconds:03}"

def get_duration_from_log(start_frame, length, frame_to_pts, sorted_frames):
    """
    Calculates duration using VFR logic: Timestamp(End) - Timestamp(Start).
    Handles edge cases where the cut goes to the very end of the video.
    """
    start_time = frame_to_pts.get(start_frame)
    if start_time is None:
        return None, None

    end_frame_idx = start_frame + length
    end_time = frame_to_pts.get(end_frame_idx)

    # If the end frame exists in log, easy math
    if end_time is not None:
        duration = end_time - start_time
    else:
        # Edge case: Cut goes to end of video. Estimate based on last frame duration.
        last_known = sorted_frames[-1]
        if len(sorted_frames) > 1:
            last_frame_dur = frame_to_pts[last_known] - frame_to_pts[sorted_frames[-2]]
        else:
            last_frame_dur = 0.04 # Fallback
        
        missing_frames = end_frame_idx - last_known
        estimated_end = frame_to_pts[last_known] + (last_frame_dur * missing_frames)
        end_time = estimated_end
        duration = end_time - start_time

    return start_time, duration

def process_vdscript(vdscript_path):
    """
    Process a single .vdscript file using its corresponding log for VFR accuracy.
    """
    vdscript_path = Path(vdscript_path)
    print(f"Processing '{vdscript_path.name}'...")

    # 1. Determine Log File Path
    # Logic: Remove "_adjusted" if present, then remove extension, add "_frame_log.txt"
    # e.g. "video_adjusted.vdscript" -> "video" -> "video_frame_log.txt"
    base_name = vdscript_path.stem
    if base_name.endswith("_adjusted"):
        base_name = base_name.replace("_adjusted", "")
    
    log_path = vdscript_path.parent / f"{base_name}_frame_log.txt"

    if not log_path.exists():
        print(f"  [Skipped] Could not find frame log: {log_path.name}")
        return

    # 2. Parse the log
    frame_to_pts, sorted_frames = parse_showinfo_log(log_path)
    if not frame_to_pts:
        print(f"  [Skipped] Log file empty or invalid: {log_path.name}")
        return

    # 3. Read the Vdscript ranges
    selections = []
    pattern = re.compile(r"VirtualDub\.subset\.AddRange\((\d+),(\d+)\);")
    
    try:
        with open(vdscript_path, 'r', encoding='utf-8') as f:
            for line in f:
                match = pattern.search(line)
                if match:
                    start_frame = int(match.group(1))
                    length = int(match.group(2))
                    selections.append((start_frame, length))
    except Exception as e:
        print(f"  Error reading vdscript: {e}")
        return

    if not selections:
        print(f"  No selections found in {vdscript_path.name}")
        return

    # 4. Generate Info Lines
    output_lines = []
    total_duration_sec = 0.0
    total_frames_count = 0
    
    # Calculate max width for alignment
    max_frames_text_len = 0
    # Pre-calculate text width to align columns perfectly
    for start_f, length in selections:
        end_f = start_f + length - 1
        txt = f"(Frames {start_f} - {end_f})"
        if len(txt) > max_frames_text_len:
            max_frames_text_len = len(txt)

    for start_frame, length in selections:
        end_frame = start_frame + length - 1
        
        # Get VFR times
        start_ts, duration = get_duration_from_log(start_frame, length, frame_to_pts, sorted_frames)
        
        if start_ts is not None:
            end_ts = start_ts + duration
            
            # Format Strings
            s_str = seconds_to_hms(start_ts)
            e_str = seconds_to_hms(end_ts)
            d_str = seconds_to_hms(duration)
            
            frames_text = f"(Frames {start_frame} - {end_frame})"
            
            # Line Format: 00:00:00 - 00:00:10 (Frames 0-100)    Length: ...
            line = f"{s_str} - {e_str} {frames_text:<{max_frames_text_len}}    Length: {d_str} ({length} frames)"
            output_lines.append(line)
            
            total_duration_sec += duration
            total_frames_count += length
        else:
            output_lines.append(f"Error finding timestamps for frames {start_frame}-{end_frame}")

    # 5. Write to _info.txt
    output_file = vdscript_path.parent / f"{vdscript_path.name.replace('.vdscript', '_info.txt')}"
    
    with open(output_file, 'w', encoding='utf-8') as f:
        for line in output_lines:
            f.write(line + "\n")
        
        f.write("-" * 80 + "\n")
        total_str = seconds_to_hms(total_duration_sec)
        f.write(f"Total Length: {total_str} ({total_frames_count} frames)\n")
        f.write("Timestamps calculated from FFmpeg frame log\n")

    print(f"  -> Generated: {output_file.name}")

def main():
    folder = Path.cwd()
    print("--- VffEdit: Vdscript Info Generator (VFR Aware) ---")
    
    vdscript_files = list(folder.glob("*.vdscript"))

    if not vdscript_files:
        print("No .vdscript files found in current folder.")
        return

    print(f"Found {len(vdscript_files)} vdscript files. Scanning for logs...")
    
    for f in vdscript_files:
        process_vdscript(f)

    print("\nBatch processing complete!")

if __name__ == "__main__":
    main()