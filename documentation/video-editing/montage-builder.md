# Montage builder — step by step

`montage_builder.py` stitches highlight clips from a **theme pool** into one or more montage videos, re-encoding to a consistent resolution (1080p landscape or 9:16 vertical).

**Script path:** `scripts/video_editing/montage_builder.py`

## Prerequisites

- [Setup](setup.md) — FFmpeg installed, folder layout created
- Clips in `montage_pool/<theme>/` (see [Clip generator — hand off](clip-generator.md#hand-off-to-montage-builder))

---

## Step 1: Build your montage pool

Create a theme folder and add `.mp4` clips (only MP4 is scanned):

```text
E:\0. Moto Vids\montage_pool\summer_rides\
  highlight_003.mp4
  highlight_012.mp4
  wheelie_clip.mp4
  ...
```

**Tips**

- Use clips you already exported from `clip_generator` (or any same-codec MP4s).
- Aim for **more clips than you need** — the builder skips clips that would exceed length limits or usage caps.

### Optional: `metadata.json` in the pool folder

If you copy metadata from highlight generation, montage selection **prioritizes** clips marked with `"acceleration": true` and uses `"timestamp"` for ordering:

```json
{
  "highlights": [
    { "file": "highlight_003.mp4", "timestamp": 142.5, "acceleration": true }
  ]
}
```

Filename fallback: `something_142.5.mp4` — timestamp parsed from the last `_` segment before `.mp4`.

---

## Step 2: Test with one montage

```powershell
cd E:\REPOS\cjm-dev\scripts\video_editing

python montage_builder.py --theme summer_rides --test
```

- Builds **exactly one** montage (ignores `--count`).
- Prompts for theme only if you omit `--theme`.
- Output example: `montages\summer_rides\summer_rides_montage_test.mp4`

Watch the log for clip count and FFmpeg progress. Press **Ctrl+C** to abort safely (FFmpeg is terminated).

---

## Step 3: Build multiple montages

```powershell
python montage_builder.py --theme summer_rides --count 5 --shuffle
```

| Flag | Effect |
|------|--------|
| `--count 5` | Up to 5 montage files: `summer_rides_montage_00.mp4` … `04` |
| `--shuffle` | Randomize clip order when filling each montage |
| (no shuffle) | Uses priority sort (acceleration + timestamp from metadata/filename) |

**Per-montage limits (defaults)**

- Max total duration: **120 seconds** (`--max-length`)
- Each source clip used at most **2 times** across all montages in one run (`max_clip_usage` in code)

---

## Step 4: Vertical montages (9:16)

```powershell
python montage_builder.py --theme summer_rides --count 3 --vertical --shuffle
```

Output suffix: `_9x16` — e.g. `summer_rides_montage_00_9x16.mp4`  
Scaled with letterbox pad to 1080×1920.

---

## Step 5: Non-interactive batch (scripts / Task Scheduler)

```powershell
python montage_builder.py --theme summer_rides --count 3 --max-length 90 --shuffle --crf 22
```

All inputs via flags — no prompts when `--theme` is set.

---

## Step 6: Find your outputs

```text
E:\0. Moto Vids\montages\summer_rides\
  summer_rides_montage_00.mp4
  summer_rides_montage_01.mp4
  ...
```

Encoded with H.264 (`libx264`), AAC audio, `faststart` for web playback.

---

## Interactive mode (no `--theme`)

```powershell
python montage_builder.py
```

1. Prompt: `Enter theme folder:` → type `summer_rides` (must exist under `montage_pool/`)
2. Prompt: `How many montages?:` → e.g. `3`

---

## Different base directory

```powershell
python montage_builder.py --base-dir "D:\Moto Vids" --theme summer_rides --count 2
```

---

## Typical end-to-end workflow

| Step | Action |
|------|--------|
| 1 | Drop raw rides in `raw\2026-05-01\` |
| 2 | `python clip_generator.py --folder 2026-05-01 --style pov` |
| 3 | Curate best clips → `montage_pool\may_rides\` |
| 4 | `python montage_builder.py --theme may_rides --count 5 --shuffle` |
| 5 | Upload `montages\may_rides\*.mp4` |

---

## Troubleshooting

| Issue | What to try |
|-------|-------------|
| Theme folder not found | Create `montage_pool\<theme>\` with at least one `.mp4` |
| No clips selected | Pool too short vs `--max-length`; add more clips or raise `--max-length` |
| Second montage empty | Clips exhausted or all hit 2-use cap; add clips or lower `--count` |
| Not enough clips for montage #2 | Normal with small pools — builder stops with message |
| Blocky output | Lower `--crf` (e.g. `18`); slower preset = better quality but slower |

Full flag list: [Reference](reference.md).
