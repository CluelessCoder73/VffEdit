"""
================================================================================
ExactCut GOP Analyzer (gop_analyzer.py)
================================================================================

# This script was tested and works with:
# - Python 3.13.7
# - VirtualDub2 (build 44282) .vdscript files
# - "FFmpeg" generated frame log files (the version in LosslessCut 3.68.0)

PURPOSE:
This script is an OCD-level safety net for your ExactCut workflow. It analyzes 
your adjusted VirtualDub script files ("_adjusted.vdscript") to determine the 
size of the starting GOP (Group of Pictures) for every single cut segment.

WHY DOES THIS MATTER?
In the ExactCut FFmpeg Cutter, we use a "Start Offset (ms)" (a Seek Nudge) to 
push FFmpeg slightly past the cut point, forcing it to snap to the correct 
keyframe. 

However, if your video has an ultra-short GOP right at the start of a segment 
(e.g., a GOP that is only 6 frames long), and your Seek Nudge is longer than 
that GOP (e.g., an 8-frame nudge), FFmpeg will jump entirely over the first 
keyframe and snap to the next one! This results in lost frames.

This script scans all your files and reports the "Smallest starting GOP" across 
all segments, warning you if your Seek Nudge might be dangerously long.

PREREQUISITES:
- Python 3.x
- Output files from vdscript_range_adjuster.py ("_adjusted.vdscript")
- Matching FFmpeg frame log files ("_frame_log.txt")

USAGE:
Run the script in the same folder as your files:
    python gop_analyzer.py

OUTPUT (gop_info.txt):
The script will generate a list of all segments and their starting GOP sizes, 
with a summary at the bottom:
    Smallest starting GOP in all vdscripts: 17 frames ("video2.mp4_adjusted.vdscript")

================================================================================
HOW TO FIX ULTRA-SHORT GOPs USING EXACTCUT FFMPEG CUTTER
================================================================================
If the "Smallest starting GOP" is comfortably larger than your intended Seek Nudge 
(e.g., the smallest GOP is 250 frames, and you are only nudging by 8 frames), 
you are perfectly safe! Do nothing.

However, if the smallest starting GOP is dangerously small (e.g., 6 frames), 
you MUST take action to avoid losing frames. You have two options:

METHOD 1: Expand the Segment using the ExactCut Editor (Recommended)
By pushing the start of the offending segment back to an earlier keyframe, you 
absorb the tiny GOP safely into the middle of the video segment.
    1. Open ExactCut FFmpeg Cutter.
    2. Open the "✏️ Editor" tool and load your `.cutlist.txt`.
    3. Look at `gop_info.txt` to identify which segment # has the tiny GOP.
    4. In the Editor, use "1. Expand Start Earlier" on that Line #. 
       (Add 1.0 or 2.0 seconds to push it safely back).
    5. Save and proceed!

METHOD 2: Lower your Seek Nudge using the Calculator
If you don't want to change your cut points, you must make your Seek Nudge 
smaller than the tiny GOP.
    1. Open ExactCut FFmpeg Cutter.
    2. Open the "🧮 Calculator" tool.
    3. Enter your video's FPS.
    4. Enter a frame count strictly LESS than the "Smallest starting GOP". 
       (e.g., If the smallest GOP is 8 frames, enter '7').
    5. Click "Calculate" and then "Set Start" to apply this ultra-small 
       nudge to your Start Offset (ms).
       
*Note: A very small Seek Nudge increases the risk of FFmpeg snapping backward 
and including unwanted video, which is why Method 1 is preferred!*
================================================================================
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

def find_next_i_frame(start_frame, end_frame, frame_types):
    for frame in range(start_frame + 1, end_frame + 1):
        if frame_types.get(frame) == 'I':
            return frame
    return None

def calculate_gop_sizes(vdscript_file, frame_types):
    gop_sizes = []
    with open(vdscript_file, 'r') as f:
        for line in f:
            if line.startswith('VirtualDub.subset.AddRange'):
                match = re.search(r'AddRange\((\d+),(\d+)\)', line)
                if match:
                    start_frame = int(match.group(1))
                    range_length = int(match.group(2))
                    end_frame = start_frame + range_length - 1
                    next_i_frame = find_next_i_frame(start_frame, end_frame, frame_types)
                    if next_i_frame:
                        gop_size = next_i_frame - start_frame
                    else:
                        gop_size = range_length
                    gop_sizes.append(gop_size)
    return gop_sizes

def batch_process_vdscripts(directory, output_file):
    all_results = []
    smallest_overall = None
    smallest_file = None
    
    with open(output_file, 'w') as outfile:
        for filename in os.listdir(directory):
            if filename.endswith('_adjusted.vdscript'):
                base_name = filename.replace('_adjusted.vdscript', '')
                frame_log_file = os.path.join(directory, f"{base_name}_frame_log.txt")
                vdscript_file = os.path.join(directory, filename)
                
                if os.path.exists(frame_log_file):
                    frame_types = read_frame_log(frame_log_file)
                    gop_sizes = calculate_gop_sizes(vdscript_file, frame_types)
                    
                    if gop_sizes:
                        # Write the vdscript name and GOP sizes
                        outfile.write(f"Name: \"{filename}\"\n")
                        for idx, size in enumerate(gop_sizes, start=1):
                            outfile.write(f"{idx} - {size}\n")
                        
                        # Calculate and write the smallest GOP size for this vdscript
                        smallest = min(gop_sizes)
                        outfile.write(f"\nSmallest starting GOP: {smallest} frames\n")
                        outfile.write("---------------------------------\n\n")
                        
                        # Track the overall smallest GOP size
                        if smallest_overall is None or smallest < smallest_overall:
                            smallest_overall = smallest
                            smallest_file = filename
                else:
                    print(f"Skipped: {filename} (No corresponding frame log file found)")
        
        # Write the overall smallest GOP size at the end
        if smallest_overall is not None:
            outfile.write("--------------------------------------------------\n")
            outfile.write("--------------------------------------------------\n")
            outfile.write(f"Smallest starting GOP in all vdscripts: {smallest_overall} frames (\"{smallest_file}\")\n")

# Main execution
directory = '.'  # Current directory, change if needed
output_file = 'gop_info.txt'

batch_process_vdscripts(directory, output_file)

print("Batch processing completed. Results written to gop_info.txt")