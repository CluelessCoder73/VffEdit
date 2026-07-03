# ==============================================================================
# HELP SECTION & WORKFLOW GUIDE
# ==============================================================================
# DESCRIPTION:
# This script is a Tkinter-based batch processor for VirtualDub (.vdscript) files.
# It provides two main features that can be used independently or together:
# 1) VirtualDub2 to VirtualDub script conversion (Direct Stream Copy).
# 2) An FPS Multiplier to scale cutlist/subset frame numbers.
#
# WHY USE VDUB2 --> VDUB CONVERSION?
# Certain video codecs do not behave correctly or fail when using "Direct Stream 
# Copy" inside VirtualDub2. A highly effective workaround is to perform all your 
# timeline edits and cuts using the modern VirtualDub2 interface, and then use this 
# script to convert the output file so that the original VirtualDub can handle the 
# final AVI export safely via Direct Stream Copy.
#
# WHY USE THE FPS MULTIPLIER? (THE PROXY WORKFLOW)
# When editing heavy 4K 60fps footage, editing can become sluggish. To fix this, 
# you can generate a lightweight, lower-resolution, lower-framerate proxy video 
# using an AviSynth (.avs) script like this:
#
#     #input video is 4K 60 fps.
#     LWLibavVideoSource("C:\my_video.mkv")
#     SelectEven() #half the frame rate (30 fps)
#     Spline36Resize(1280, 720)
#
# You then load this 30fps proxy into VirtualDub2 to do your cutting and editing. 
# Because the proxy runs at 30fps, the frame numbers saved in the .vdscript will 
# be exactly half of what they should be for the original 4K 60fps video.
#
# By running your saved .vdscript through this tool with a "2X" FPS Multiplier, 
# the script automatically multiplies every frame number in the cutlist. This 
# scales your edits perfectly back up to match the original 60fps timeline.
# ==============================================================================

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import re
import os

class VDubProcessorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("VirtualDub Script Batch Processor")
        self.root.geometry("450x350")
        self.root.resizable(False, False)
        
        self.file_paths = []

        # --- UI Elements ---
        
        # 1. File Selection
        self.lbl_files = tk.Label(root, text="No files selected", fg="gray")
        self.lbl_files.pack(pady=(15, 5))
        
        self.btn_browse = tk.Button(root, text="Browse for .vdscript files", command=self.browse_files)
        self.btn_browse.pack(pady=5)
        
        # Separator
        ttk.Separator(root, orient='horizontal').pack(fill='x', padx=20, pady=15)
        
        # 2. VDub2 -> VDub Conversion Checkbox
        self.var_convert = tk.BooleanVar(value=False) # Unchecked by default
        self.chk_convert = tk.Checkbutton(
            root, 
            text="Convert VDub2 to VDub (Direct stream copy)", 
            variable=self.var_convert
        )
        self.chk_convert.pack(pady=5)
        
        # 3. FPS Multiplier Dropdown
        tk.Label(root, text="FPS Multiplier (Cutlist adjustment):").pack(pady=(10, 0))
        
        self.var_fps = tk.StringVar(value="1X")
        self.fps_dropdown = ttk.Combobox(
            root, 
            textvariable=self.var_fps, 
            values=["1X", "2X", "4X", "8X", "16X"],
            state="readonly",
            width=10
        )
        self.fps_dropdown.pack(pady=5)
        
        # Separator
        ttk.Separator(root, orient='horizontal').pack(fill='x', padx=20, pady=15)
        
        # 4. Process Button
        self.btn_process = tk.Button(root, text="Process Files", command=self.process_files, bg="green", fg="white", font=("Arial", 10, "bold"))
        self.btn_process.pack(pady=10)

    def browse_files(self):
        files = filedialog.askopenfilenames(
            title="Select .vdscript files",
            filetypes=(("VirtualDub Scripts", "*.vdscript"), ("All Files", "*.*"))
        )
        if files:
            self.file_paths = list(files)
            count = len(self.file_paths)
            self.lbl_files.config(text=f"{count} file(s) selected", fg="black")

    def process_files(self):
        if not self.file_paths:
            messagebox.showwarning("No Files", "Please select at least one .vdscript file to process.")
            return
            
        # Get multiplier integer (e.g., "2X" -> 2)
        multiplier = int(self.var_fps.get().replace('X', ''))
        do_conversion = self.var_convert.get()
        
        processed_count = 0
        
        for filepath in self.file_paths:
            try:
                with open(filepath, 'r') as file:
                    lines = file.readlines()
                    
                converted_lines = []
                past_subset_clear = False
                
                for line in lines:
                    # Logic 1: VDub2 to VDub Conversion
                    if do_conversion:
                        if "VirtualDub.video.SetMode(3);" in line:
                            line = line.replace("VirtualDub.video.SetMode(3);", "VirtualDub.video.SetMode(0);")
                        elif any(skip_cmd in line for skip_cmd in [
                            "VirtualDub.SaveFormatAVI();",
                            "VirtualDub.SaveAudioFormat(\"\");",
                            "VirtualDub.video.filters.BeginUpdate();",
                            "VirtualDub.video.filters.EndUpdate();"
                        ]):
                            continue # Skip adding this line
                            
                    # Logic 2: FPS Multiplier
                    if "VirtualDub.subset.Clear();" in line:
                        past_subset_clear = True
                        converted_lines.append(line)
                        continue
                        
                    if past_subset_clear and multiplier > 1:
                        # Find all numbers in the line and multiply them
                        # The lambda function takes the regex match, converts it to an int, multiplies it, and returns it as a string
                        line = re.sub(r'\d+', lambda m: str(int(m.group(0)) * multiplier), line)
                        
                    converted_lines.append(line)
                    
                # Save the new file with a "_processed" suffix
                dir_name, file_name = os.path.split(filepath)
                name, ext = os.path.splitext(file_name)
                new_filename = f"{name}_processed{ext}"
                new_filepath = os.path.join(dir_name, new_filename)
                
                with open(new_filepath, 'w') as file:
                    file.writelines(converted_lines)
                    
                processed_count += 1
                
            except Exception as e:
                messagebox.showerror("Error", f"An error occurred while processing {filepath}:\n\n{str(e)}")
                return
                
        messagebox.showinfo("Success", f"Successfully processed {processed_count} file(s)!\n\nFiles have been saved in their original folders with '_processed' appended to the name.")
        
        # Reset UI
        self.file_paths = []
        self.lbl_files.config(text="No files selected", fg="gray")

if __name__ == "__main__":
    root = tk.Tk()
    app = VDubProcessorApp(root)
    root.mainloop()