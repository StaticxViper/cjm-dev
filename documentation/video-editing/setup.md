# Video editing setup

One-time setup before using `clip_generator.py` or `montage_builder.py`.

## Step 1: Install FFmpeg

Both scripts call `ffmpeg` and `ffprobe` from your PATH.

1. Download FFmpeg for Windows from [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html) (or use `winget install ffmpeg`).
2. Open a **new** terminal and verify:

```powershell
ffmpeg -version
ffprobe -version
```

If either command is not found, add FFmpeg’s `bin` folder to your system PATH and restart the terminal.

## Step 2: Choose your video root folder

All media paths hang off a single **base directory**. Default:

```text
E:\0. Moto Vids
```

To use a different drive or folder, either:

- Pass `--base-dir "D:\Moto Vids"` on every run, or
- Set environment variable `MOTO_VIDS_BASE`:

```powershell
$env:MOTO_VIDS_BASE = "D:\Moto Vids"
```

## Step 3: Create the folder layout

Under your base directory, create:

```text
E:\0. Moto Vids\
  raw\                 ← put ride folders here
  highlights\          ← created by clip_generator
  splits\              ← created by clip_generator (optional)
  montage_pool\        ← you copy favorite clips here
  montages\            ← created by montage_builder
```

**Raw footage layout** — one folder per ride day (or session):

```text
raw\
  2026-05-01\
    GOPR0001.mp4
    GOPR0002.mp4
  2026-05-15\
    ride_front.mp4
```

Folder names are arbitrary strings; `clip_generator` lists subfolders of `raw/` when you pick interactively.

## Step 4: Python environment

From the repo root (if you use a venv, activate it first):

```powershell
cd E:\REPOS\cjm-dev
pip install -r requirements/requirements.txt
```

The video scripts use only the Python standard library (no extra pip packages for these two files).

## Step 5: Open the scripts directory (optional)

```powershell
cd E:\REPOS\cjm-dev\scripts\video_editing
```

Scripts can be run from any working directory; paths to videos are absolute or resolved from `--base-dir`.

## Next steps

- [Clip generator — full walkthrough](clip-generator.md)
- [Montage builder — full walkthrough](montage-builder.md)
