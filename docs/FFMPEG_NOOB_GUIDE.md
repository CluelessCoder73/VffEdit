# FFmpeg for Beginners: A Quick Start Guide

Welcome to the powerful world of FFmpeg! While it might seem intimidating, FFmpeg is the engine that makes the VffEdit workflow possible. This guide will show you how to set it up using the tools you already have.

---

## 1. Easy Setup (The LosslessCut Method)

If you are using **LosslessCut**, you already have FFmpeg on your computer! You don't need to download anything else. You just need to tell Windows where it is.

1. **Find your FFmpeg:** Open your LosslessCut folder. Go to:
`resources` > `ffmpeg.exe`
2. **Copy the Path:** Click the address bar at the top of that folder and copy the text (e.g., `C:\Desktop\LosslessCut-win-x64\resources`).
3. **Add to Windows PATH:**
* Search Windows for **"Edit the system environment variables."**
* Click **Environment Variables** > Find **Path** in the "System variables" list > Click **Edit**.
* Click **New** and paste the path you copied.
* **Verify:** Open a Command Prompt (cmd) and type `ffmpeg -version`. If text appears, you are ready to go!



---

## 2. Essential Commands for VffEdit

### A. The "Remux" (Fixing Video Containers)

If your video is in a format that doesn't work well with VirtualDub2 (like `.ts`, `.flv`, or `.m2ts`), you can move it into a modern `.mp4` or `.mkv` container instantly without losing any quality.

```bash
ffmpeg -i "input_video.ts" -c copy "output_video.mp4"

```

* `-c copy`: This is "Stream Copy" mode. It is 100% lossless and very fast.

### B. Changing Audio (Transcoding)

If your source video has an audio format your TV or editor doesn't support (like DTS or Opus), you can keep the video lossless but change the audio to standard AAC.

```bash
ffmpeg -i "input.mp4" -c:v copy -c:a aac -b:a 192k "output.mp4"

```

* `-c:v copy`: Keeps the video 100% original.
* `-c:a aac`: Converts the audio to a standard format.

---

## 3. Dealing with "Suspicious Timestamps"

When you run `vfr_detector.pyw`, you might see a warning about **"SUSPICIOUS TIMESTAMPS."**

### Step 1: Adjust the Tolerance

Don't panic! Most of the time, this is just "jitter" from a smartphone (like a Blackview or iPhone).

1. Open the VFR Detector GUI.
2. Change **Duration Tolerance** from `0.001` to **`0.002`**.
3. Run the check again. If it now says **"VFR HEALTHY,"** you are safe to proceed!

### Step 2: The Timescale Fix

If the detector still shows dozens of unique duration groups even with a higher tolerance, the file's internal clock is likely messy. You can "clean" the timeline with this command:

```bash
ffmpeg -i "jittery_video.mp4" -c copy -video_track_timescale 90k "fixed_video.mp4"

```

* This resets the video's internal timing clock to a standard frequency (90kHz), which often resolves "ghost" frame errors during cutting.

---

## 4. Pro-Tips for Success

* **Use Quotes:** If your filename has spaces (e.g., `My Video.mp4`), always put it in double quotes: `"My Video.mp4"`.
* **Don't Re-encode:** Unless you specifically want to reduce the file size or change quality, always try to use `-c copy`. It preserves your original quality and saves hours of time.
* **Output Names:** FFmpeg won't automatically overwrite files. If you want to overwrite a file without being asked, add `-y` to the start of your command (e.g., `ffmpeg -y -i ...`).

---
