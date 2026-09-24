import os
import re
import argparse

# ==============================================================================
# User Guide for vdscript_range_adjuster.py
# ==============================================================================
#
# Purpose:
# This script is designed to adjust cut points in VirtualDub & VirtualDub2 script files (.vdscript)
# to ensure they align with legal frame boundaries, particularly useful when working with proxy
# or high-resolution footage. It guarantees that no frames are lost in the process, unlike most
# "stream copy" video editors. No need for manually aligning cut points with keyframes, because
# this script does all that for you automatically using PTS timestamps (VFR-safe). Now works in batch mode!
#
# Features:
# - Adjusts start points to previous I-frames. If the start point is already on an I-frame, it is left untouched.
#   Alternatively, you can adjust the start point to the "2nd" previous I-frame (offset = 2). In that case,
#   if the start point is already on an I-frame, it is instead adjusted to just the previous I-frame.
#   Can be useful when working with x265 & other "open GOP" codecs, where cut-in points end up corrupted,
#   & the video doesn't play right again until the next I-frame.
#   In fact, you can go further back in I-frames, but offset = 2 handles open GOP issues cleanly.
#
# - Adjusts endpoints to the next P or I-frame (Standard mode). If the endpoint is already on a P or I-frame,
#   it is left untouched. Alternatively, enabling Full GOP mode (--fullgop) adjusts the endpoint to the last
#   P-frame before the next I-frame.
#
# - Automatic Tiny GOP Detection & Pushback: Detects GOP durations equal to or below the tiny GOP threshold
#   (default: 0.2s) and automatically applies a pushback nudge (default: 1.0s) to snap to a preceding safe I-frame,
#   preventing unsafe tiny GOP cuts and playback glitches.
#
# - Merges overlapping or close ranges based on direct PTS timestamp differences in seconds (optional).
#
# Prerequisites:
# - Python 3.x installed on your system
# - Input .vdscript file(s) from VirtualDub or VirtualDub2 (source_video_filename.extension.vdscript)
# - Frame log file (source_video_filename.extension_frame_log.txt) containing frame type & PTS timestamp information
#
# Configuration & CLI Arguments:
# Parameters can be passed via command-line flags or configured in __main__:
#
#   --dir <path>         : Directory to process (default: '.')
#   --offset <int>       : Number of I-frames to go back for start points (default: 1)
#   --mingap <float>     : Minimum gap in seconds to keep ranges separate when merging (default: 5.0)
#   --tinygop <float>    : Tiny GOP duration threshold in seconds (default: 0.2)
#   --pushback <float>   : Pushback nudge duration in seconds when a tiny GOP is detected (default: 1.0)
#   --fullgop            : Enable Full GOP mode (moves endpoints to last P-frame before next I-frame)
#
# In-script parameters (located in __main__):
#   directory            : Defaults to current directory ('.')
#   i_frame_offset       : Number of I-frames to go back for start points (default: 1)
#   merge_ranges_option  : Set to True to enable merging of close ranges, False to disable
#   min_gap_sec          : Minimum gap in seconds to keep ranges separate when merging (default: 5.0)
#   tinygop              : Tiny GOP threshold in seconds (default: 0.2)
#   pushback             : Pushback nudge duration in seconds (default: 1.0)
#   full_gop_mode        : Set to False for standard mode (next P/I-frame), True for Full GOP mode
#
# Output:
# The script generates new _adjusted.vdscript files with the adjusted cut points. These files can
# then be used directly in VirtualDub or VirtualDub2 (depending on which version created the original vdscript files!).
#
# Tips for Optimal Use:
# - When editing, place cut points freely without worrying about exact frame types or keyframe alignment.
# - Use this script to adjust the cut points before applying them to your high-resolution footage.
# - Keep tiny GOP detection enabled so edge-case cuts near keyframe boundaries are automatically pushed back to safe I-frames.
#
# Troubleshooting:
# - If the script fails to run, ensure you have Python 3.x installed and required arguments formatted correctly.
# - If cut points seem incorrect, double-check your frame log (_frame_log.txt) to ensure it matches your video file and contains pts_time data.
# - For videos with unusual or open GOP structures, you may need to set --offset to 2.
#
# This script provides a powerful solution for ensuring accurate, VFR-safe, lossless cuts in your video editing workflow,
# especially when working with proxy videos for high-resolution content. By automating the adjustment of cut points
# to legal frame boundaries and resolving tiny GOP edge cases, it saves time and guarantees the integrity of your final edit.
# ==============================================================================

def read_frame_log(file_path):
    """
    Parses frame log to extract frame numbers, frame types, and PTS timestamps.
    Returns a dictionary mapping frame_num -> {'type': str, 'pts': float}
    """
    frame_data = {}
    with open(file_path, 'r') as f:
        for line in f:
            if 'Parsed_showinfo_0' in line:
                match = re.search(r'n:\s*(\d+).*?pts_time:\s*([\d\.-]+).*?type:\s*(\w)', line)
                if match:
                    frame_num = int(match.group(1))
                    pts_time = float(match.group(2))
                    frame_type = match.group(3)
                    frame_data[frame_num] = {
                        'type': frame_type,
                        'pts': pts_time
                    }
    return frame_data

def find_nth_previous_i_frame(frame_num, frame_data, n):
    i_frames_found = 0
    while frame_num >= 0:
        if frame_data.get(frame_num, {}).get('type') == 'I':
            i_frames_found += 1
            if i_frames_found == n:
                return frame_num
        frame_num -= 1
    return 0  # Return frame 0 if not enough I-frames are found

def find_next_i_frame(frame_num, frame_data):
    max_frame = max(frame_data.keys()) if frame_data else 0
    curr = frame_num + 1
    while curr <= max_frame:
        if frame_data.get(curr, {}).get('type') == 'I':
            return curr
        curr += 1
    return None

def find_next_p_or_i_frame(frame_num, frame_data):
    max_frame = max(frame_data.keys()) if frame_data else 0
    if frame_data.get(frame_num, {}).get('type') in ['I', 'P']:
        return frame_num
    next_frame = frame_num + 1
    while next_frame <= max_frame:
        if frame_data.get(next_frame, {}).get('type') in ['I', 'P']:
            return next_frame
        next_frame += 1
    return frame_num

def find_last_p_frame_before_next_i(frame_num, frame_data):
    max_frame = max(frame_data.keys()) if frame_data else 0
    last_p_frame = None
    while frame_num <= max_frame:
        if frame_data.get(frame_num, {}).get('type') == 'I' and last_p_frame is not None:
            return last_p_frame
        if frame_data.get(frame_num, {}).get('type') == 'P':
            last_p_frame = frame_num
        frame_num += 1
    return last_p_frame if last_p_frame is not None else max_frame

def find_frame_by_pts(target_pts, frame_data):
    """
    Finds the frame matching or immediately preceding target_pts (VFR safe lookup).
    """
    if target_pts <= 0:
        return 0
    best_frame = 0
    for f_num in sorted(frame_data.keys()):
        if frame_data[f_num]['pts'] <= target_pts:
            best_frame = f_num
        else:
            break
    return best_frame

def adjust_range(start, length, frame_data, i_frame_offset, full_gop_mode, tinygop_threshold, pushback_sec):
    # Step 1: Initial start point alignment
    new_start = find_nth_previous_i_frame(start, frame_data, i_frame_offset)
    pushback_triggered = False

    # Step 2: Time-based Tiny GOP Detection & 1-second single pushback
    next_i = find_next_i_frame(new_start, frame_data)
    if next_i is not None and new_start in frame_data and next_i in frame_data:
        gop_duration = frame_data[next_i]['pts'] - frame_data[new_start]['pts']
        if gop_duration <= tinygop_threshold:
            pushback_triggered = True
            # Subtract pushback_sec from target PTS and find preceding frame
            target_pts = frame_data[new_start]['pts'] - pushback_sec
            target_frame = find_frame_by_pts(target_pts, frame_data)
            # Snap to preceding I-frame once
            new_start = find_nth_previous_i_frame(target_frame, frame_data, i_frame_offset)

    # Step 3: End point alignment
    end = start + length - 1
    if full_gop_mode:
        new_end = find_last_p_frame_before_next_i(end, frame_data)
    else:
        new_end = find_next_p_or_i_frame(end, frame_data)

    new_end = max(new_end, new_start)
    new_length = new_end - new_start + 1
    return new_start, new_length, pushback_triggered

def merge_ranges(raw_ranges_data, min_gap_sec, frame_data):
    """
    Merges close ranges using direct PTS timestamp differences.
    Tracks merged metadata to map pushbacks correctly to adjusted range indices.
    """
    if not raw_ranges_data:
        return []

    # raw_ranges_data item: (start, length, pushed_bool)
    first_start, first_len, first_pushed = raw_ranges_data[0]
    
    merged = [{
        'range': (first_start, first_len),
        'pushed': first_pushed,
        'merged_count': 1
    }]

    for current in raw_ranges_data[1:]:
        curr_start, curr_len, curr_pushed = current
        previous = merged[-1]
        
        prev_start, prev_len = previous['range']
        prev_end_frame = prev_start + prev_len - 1

        if prev_end_frame in frame_data and curr_start in frame_data:
            gap_sec = frame_data[curr_start]['pts'] - frame_data[prev_end_frame]['pts']
        else:
            gap_sec = float('inf')

        if gap_sec <= min_gap_sec:
            new_end_frame = max(prev_end_frame, curr_start + curr_len - 1)
            previous['range'] = (prev_start, new_end_frame - prev_start + 1)
            previous['pushed'] = previous['pushed'] or curr_pushed
            previous['merged_count'] += 1
        else:
            merged.append({
                'range': (curr_start, curr_len),
                'pushed': curr_pushed,
                'merged_count': 1
            })

    return merged

def process_vdscript(input_file, output_file, frame_data, i_frame_offset, merge_option, min_gap_sec, full_gop_mode, tinygop_threshold, pushback_sec):
    raw_ranges_data = []

    with open(input_file, 'r') as infile:
        input_lines = infile.readlines()

    for line in input_lines:
        if line.startswith('VirtualDub.subset.AddRange'):
            match = re.search(r'AddRange\((\d+),(\d+)\)', line)
            if match:
                start, length = int(match.group(1)), int(match.group(2))
                new_start, new_length, pushed = adjust_range(
                    start, length, frame_data, i_frame_offset, 
                    full_gop_mode, tinygop_threshold, pushback_sec
                )
                raw_ranges_data.append((new_start, new_length, pushed))

    if merge_option:
        final_structures = merge_ranges(raw_ranges_data, min_gap_sec, frame_data)
    else:
        final_structures = [{
            'range': (r[0], r[1]),
            'pushed': r[2],
            'merged_count': 1
        } for r in raw_ranges_data]

    pushed_info = []
    final_ranges = []

    for idx, item in enumerate(final_structures, start=1):
        final_ranges.append(item['range'])
        if item['pushed']:
            if item['merged_count'] > 1:
                pushed_info.append(f"#{idx} (merged range)")
            else:
                pushed_info.append(f"#{idx}")

    with open(output_file, 'w') as outfile:
        for line in input_lines:
            if not line.startswith('VirtualDub.subset.AddRange') and not line.startswith('VirtualDub.video.SetRange'):
                outfile.write(line)

        for start, length in final_ranges:
            outfile.write(f'VirtualDub.subset.AddRange({start},{length});\n')

        outfile.write('VirtualDub.video.SetRange();\n')

    return pushed_info

def batch_process_vdscripts(directory, i_frame_offset, merge_ranges_option, min_gap_sec, full_gop_mode, tinygop_threshold, pushback_sec):
    for filename in os.listdir(directory):
        if filename.endswith('.vdscript') and not filename.endswith('_adjusted.vdscript'):
            input_vdscript = os.path.join(directory, filename)
            frame_log_file = os.path.join(directory, f"{os.path.splitext(filename)[0]}_frame_log.txt")
            output_vdscript = os.path.join(directory, f"{os.path.splitext(filename)[0]}_adjusted.vdscript")

            if os.path.exists(frame_log_file):
                frame_data = read_frame_log(frame_log_file)
                pushed_info = process_vdscript(
                    input_vdscript, output_vdscript, frame_data, 
                    i_frame_offset, merge_ranges_option, min_gap_sec, 
                    full_gop_mode, tinygop_threshold, pushback_sec
                )
                
                out_filename = os.path.basename(output_vdscript)
                if pushed_info:
                    info_str = ", ".join(pushed_info)
                    print(f"Processed: {filename} -> {out_filename} [Pushback applied to {out_filename} range(s): {info_str}]")
                else:
                    print(f"Processed: {filename} -> {out_filename} [No Pushback needed]")
            else:
                print(f"Skipped: {filename} (No corresponding frame log file found)")

if __name__ == "__main__":
    # Standard Default Settings
    full_gop_mode = False  # Set to True if you want Full GOP Mode enabled by default
    merge_ranges_option = True

    parser = argparse.ArgumentParser(description="VffEdit Range Adjuster")
    parser.add_argument("--dir", type=str, default=".", help="Directory to process")
    parser.add_argument("--offset", type=int, default=1, help="I-frame offset")
    parser.add_argument("--mingap", type=float, default=5.0, help="Minimum gap between ranges in seconds")
    parser.add_argument("--tinygop", type=float, default=0.2, help="Tiny GOP duration threshold in seconds")
    parser.add_argument("--pushback", type=float, default=1.0, help="Nudge pushback duration in seconds")
    parser.add_argument("--fullgop", action="store_true", help="Enable Full GOP Mode")
    args = parser.parse_args()

    if args.fullgop:
        full_gop_mode = True

    print(f"Starting Range Adjuster (Offset: {args.offset}, Min Gap: {args.mingap}s, TinyGOP Threshold: {args.tinygop}s, Pushback: {args.pushback}s, Full GOP Mode: {full_gop_mode})")
    batch_process_vdscripts(
        args.dir, args.offset, merge_ranges_option, 
        args.mingap, full_gop_mode, args.tinygop, args.pushback
    )
    print("Batch processing completed.")