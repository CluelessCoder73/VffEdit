"""
User Guide for vdscript_range_adjuster.py
Purpose
This script is designed to adjust cut points in VirtualDub & VirtualDub2 script files (.vdscript) to ensure they align with legal frame boundaries, particularly useful when working with proxy videos for editing high-resolution footage. It guarantees that no frames are lost in the process, unlike most "stream copy" video editors. No need for aligning cut points with keyframes etc, because this script does all that for you automatically! After generating the adjusted .vdscript file, you can convert it to a Cuttermaran project file, an MKVToolNix GUI cutlist, or a *VffEdit FFmpeg Cutter cutlist via *vdscript_to_timecode_cutlist_generator.py (*included). More info at the bottom of this guide.
This script now works in batch mode!

Features:

# - Adjusts start points to previous I-frames. If the start point is already on an I-frame, it is left untouched. 
    Alternatively, you can also adjust the start point to the "2nd" previous I-frame (the I-frame before the previous one). In that case, if the start point is already on an I-frame, it is instead adjusted to just the previous I-frame. Can be useful when working with x265 & other "open GOP" codecs, where cut-in points end up corrupted, & the video doesn't play right again until the next I-frame.
    In fact, you can go furter back in I-frames, but I don't see any need (so far) to go any further back than 2.

	# - Adjusts endpoints to the next P or I-frame. If the endpoint is already on a P or I-frame, it is left untouched.
    Alternatively, you can also adjust the endpoint to the last P-frame before the next I-frame ("short_cut_mode = False"). In that case, if, e.g., the endpoint is already on the last P-frame before the next I-frame, it is left untouched.
    
# - Merges overlapping or close ranges (optional)

Prerequisites

    Python 3.x installed on your system
    Input .vdscript file(s) from VirtualDub or VirtualDub2 (source_video_filename.extension.vdscript)
    Frame log file (source_video_filename.extension_frame_log.txt) containing frame type information

Configuration
At the bottom of the script, you'll find several configurable parameters:

directory = '.'
i_frame_offset = 1
merge_ranges_option = True
min_gap_between_ranges = 150
short_cut_mode = True

Adjust these parameters as needed:

    directory: Defaults to current directory, change if needed
    i_frame_offset: Number of I-frames to go back for start points (default: 1)
    merge_ranges_option: Set to True to enable merging of close ranges, False to disable
    min_gap_between_ranges: Minimum gap (in frames) to keep ranges separate when merging
    short_cut_mode: Set to True to enable moving endpoints to the next P or I-frame, False for "full GOP mode"

Output
The script generates new .vdscript files with the adjusted cut points. These files can then be used directly in VirtualDub or VirtualDub2 (depending on which version created the original vdscript files!), or converted to other formats like .cpf (Cuttermaran project files), "MKVToolNix GUI" cutlists or "VffEdit FFmpeg Cutter" cutlists.
Tips for Optimal Use

    When editing proxy videos, place cut points freely without worrying about exact frame types.
    Use this script to adjust the cut points before applying them to your high-resolution footage.
    Experiment with the i_frame_offset value to find the best balance between accuracy and avoiding potential corruption from open GOP structures.

Troubleshooting

    If the script fails to run, ensure you have Python 3.x installed.
    If cut points seem incorrect, double-check your frame log to ensure it matches your video file.
    For videos with unusual GOP structures, you may need to adjust the i_frame_offset.

Converting Output to Other Formats
After generating the adjusted .vdscript file, you can convert it to other formats:

    For Cuttermaran: Use "vdscript_to_cpf".
    For MKVToolNix GUI: Use "vdscript_to_mkvtoolnix".
    For VffEdit FFmpeg Cutter: Use `vdscript_to_timecode_cutlist_generator.py` (both included).
    All are available at https://github.com/CluelessCoder73?tab=repositories

This script provides a powerful solution for ensuring accurate, lossless cuts in your video editing workflow, especially when working with proxy videos for high-resolution content. By automating the adjustment of cut points to legal frame boundaries, it saves time and guarantees the integrity of your final edit.
"""
import os
import re

def read_frame_log(file_path):
    frame_types = {}
    with open(file_path, 'r') as f:
        for line in f:
            if 'Parsed_showinfo_0' in line:
                match = re.search(r'n:\s*(\d+).*type:(\w)', line)
                if match:
                    frame_num, frame_type = int(match.group(1)), match.group(2)
                    frame_types[frame_num] = frame_type
    return frame_types

def find_nth_previous_i_frame(frame_num, frame_types, n):
    i_frames_found = 0
    while frame_num >= 0:
        if frame_types.get(frame_num) == 'I':
            i_frames_found += 1
            if i_frames_found == n:
                return frame_num
        frame_num -= 1
    return 0  # Return 0 if we can't find enough I-frames

def find_last_p_frame_before_next_i(frame_num, frame_types):
    max_frame = max(frame_types.keys())
    last_p_frame = None
    while frame_num <= max_frame:
        if frame_types.get(frame_num) == 'I' and last_p_frame is not None:
            return last_p_frame
        if frame_types.get(frame_num) == 'P':
            last_p_frame = frame_num
        frame_num += 1
    return last_p_frame if last_p_frame is not None else max_frame

def adjust_range(start, length, frame_types, i_frame_offset, short_cut_mode):
    new_start = find_nth_previous_i_frame(start, frame_types, i_frame_offset)
    end = start + length - 1
    
    if short_cut_mode:
        new_end = find_next_p_or_i_frame(end, frame_types)
    else:
        new_end = find_last_p_frame_before_next_i(end, frame_types)
    
    new_length = new_end - new_start + 1
    return new_start, new_length

def find_next_p_or_i_frame(frame_num, frame_types):
    max_frame = max(frame_types.keys())
    if frame_types.get(frame_num) in ['I', 'P']:
        return frame_num  # Return the current frame if it's already I or P
    next_frame = frame_num + 1
    while next_frame <= max_frame:
        if frame_types.get(next_frame) in ['I', 'P']:
            return next_frame
        next_frame += 1
    return frame_num  # Return original frame if no next I or P frame found

def merge_ranges(ranges, min_gap):
    if not ranges:
        return []
    
    merged = [ranges[0]]
    for current in ranges[1:]:
        previous = merged[-1]
        if current[0] - (previous[0] + previous[1]) <= min_gap:
            merged[-1] = (previous[0], max(previous[0] + previous[1], current[0] + current[1]) - previous[0])
        else:
            merged.append(current)
    
    return merged

def process_vdscript(input_file, output_file, frame_types, i_frame_offset, merge_option, min_gap, short_cut_mode):
    ranges = []
    
    infile = open(input_file, 'r')
    input_lines = infile.readlines()
    infile.close()

    for line in input_lines:
        if line.startswith('VirtualDub.subset.AddRange'):
            match = re.search(r'AddRange\((\d+),(\d+)\)', line)
            if match:
                start, length = int(match.group(1)), int(match.group(2))
                new_start, new_length = adjust_range(start, length, frame_types, i_frame_offset, short_cut_mode)
                ranges.append((new_start, new_length))

    if merge_option:
        ranges = merge_ranges(ranges, min_gap)

    with open(output_file, 'w') as outfile:
        for line in input_lines:
            if not line.startswith('VirtualDub.subset.AddRange') and not line.startswith('VirtualDub.video.SetRange'):
                outfile.write(line)

        # Write the adjusted ranges first
        for start, length in ranges:
            outfile.write(f'VirtualDub.subset.AddRange({start},{length});\n')

        # Write the VirtualDub.video.SetRange() line last
        outfile.write('VirtualDub.video.SetRange();\n')

def batch_process_vdscripts(directory, i_frame_offset, merge_ranges_option, min_gap_between_ranges, short_cut_mode):
    for filename in os.listdir(directory):
        if filename.endswith('.vdscript'):
            input_vdscript = os.path.join(directory, filename)
            frame_log_file = os.path.join(directory, f"{os.path.splitext(filename)[0]}_frame_log.txt")
            output_vdscript = os.path.join(directory, f"{os.path.splitext(filename)[0]}_adjusted.vdscript")
            
            if os.path.exists(frame_log_file):
                frame_types = read_frame_log(frame_log_file)
                process_vdscript(input_vdscript, output_vdscript, frame_types, i_frame_offset, merge_ranges_option, min_gap_between_ranges, short_cut_mode)
                print(f"Processed: {filename}")
            else:
                print(f"Skipped: {filename} (No corresponding frame log file found)")

import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VffEdit Range Adjuster")
    parser.add_argument("--dir", type=str, default=".", help="Directory to process")
    parser.add_argument("--offset", type=int, default=1, help="I-frame offset")
    parser.add_argument("--mingap", type=int, default=150, help="Minimum gap between ranges")
    parser.add_argument("--fullgop", action="store_true", help="Enable Full GOP Mode (short_cut_mode = False)")
    args = parser.parse_args()

    merge_ranges_option = True
    short_cut_mode = not args.fullgop

    print(f"Starting Range Adjuster (Offset: {args.offset}, Min Gap: {args.mingap}, Short Cut Mode: {short_cut_mode})")
    batch_process_vdscripts(args.dir, args.offset, merge_ranges_option, args.mingap, short_cut_mode)
    print("Batch processing completed.")
