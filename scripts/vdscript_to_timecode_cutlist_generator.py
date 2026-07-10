import os
import re
from pathlib import Path

# --- VffEdit: VFR-Aware Cutlist Generator ---
# Updated to support Variable Frame Rate (VFR) by calculating 
# exact durations from frame timestamps rather than a fixed FPS.
# CLEAN VERSION: No headers, just data.

def parse_showinfo_log(log_path):
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
        print(f"Error parsing showinfo log '{log_path}': {e}")
        return None, None
    
    if not frame_to_pts:
        return {}, []

    return frame_to_pts, sorted(frame_to_pts.keys())

def main():
    print("--- VffEdit: VFR Cutlist Generator (Clean Format) ---")
    script_dir = Path.cwd()
    
    adjusted_vdscript_suffix = "_adjusted.vdscript" 
    all_files_in_dir = [f for f in script_dir.iterdir() if f.is_file()]
    adjusted_vdscripts = [f for f in all_files_in_dir if f.name.endswith(adjusted_vdscript_suffix)]

    if not adjusted_vdscripts:
        print(f"No files ending with '{adjusted_vdscript_suffix}' found.")
        return

    print(f"Found {len(adjusted_vdscripts)} adjusted vdscript(s).")
    generated_count = 0

    for vdscript_path in adjusted_vdscripts:
        print(f"\nProcessing '{vdscript_path.name}'...")
        base_name = vdscript_path.name.replace(adjusted_vdscript_suffix, "")
        log_path = script_dir / f"{base_name}_frame_log.txt"
        output_path = script_dir / f"{base_name}.cutlist.txt"

        if not log_path.is_file():
            print(f"Warning: Log '{log_path.name}' not found. Skipping.")
            continue

        frame_to_pts, sorted_frames = parse_showinfo_log(log_path)
        if not frame_to_pts:
            continue

        # Parse Vdscript Ranges
        vdscript_pattern = re.compile(r'VirtualDub\.subset\.AddRange\((\d+),\s*(\d+)\);')
        ranges = []
        try:
            with open(vdscript_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    match = vdscript_pattern.search(line)
                    if match:
                        ranges.append((int(match.group(1)), int(match.group(2))))
        except Exception:
            continue
            
        if not ranges:
            continue

        # Generate Timecodes
        segments = []
        for i, (start_f, length) in enumerate(ranges):
            start_ts = frame_to_pts.get(start_f)
            if start_ts is None:
                print(f"Warning: Missing PTS for frame {start_f}. Skipping.")
                continue
            
            # Calculate Duration
            end_f_idx = start_f + length
            end_ts = frame_to_pts.get(end_f_idx)

            if end_ts is not None:
                duration = end_ts - start_ts
            else:
                # End-of-video estimation
                last_f = sorted_frames[-1]
                last_dur = 0.04
                if len(sorted_frames) > 1:
                    last_dur = frame_to_pts[last_f] - frame_to_pts[sorted_frames[-2]]
                
                missing = end_f_idx - last_f
                est_end = frame_to_pts[last_f] + (last_dur * missing)
                duration = est_end - start_ts

            segments.append(f"start_time={start_ts:.6f},duration={duration:.6f}") 
            print(f"  - Seg {i+1}: {start_ts:.3f}s (Dur: {duration:.3f}s)")

        # Write Clean Cutlist (No Header)
        if segments:
            try:
                with open(output_path, 'w') as f:
                    for line in segments:
                        f.write(line + "\n")
                print(f"Saved: '{output_path.name}'")
                generated_count += 1
            except Exception as e:
                print(f"Error writing: {e}")

    print(f"\nDone. Generated {generated_count} cutlist(s).")

if __name__ == "__main__":
    main()