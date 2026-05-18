# Clip generator — step by step

`clip_generator.py` finds exciting moments in motorcycle ride footage using **scene-change detection** (motion) and **audio RMS spikes** (revs/acceleration), then exports short MP4 highlights.

**Script path:** `scripts/video_editing/clip_generator.py`

## What it produces

For each source video:

| Output | Location |
|--------|----------|
| Highlight clips | `highlights/<label>/<video_stem>/highlight_000.mp4`, … |
| Metadata | `highlights/<label>/<video_stem>/metadata.json` |
| Split segments (optional) | `splits/<label>/<video_stem>/split_000.mp4`, … |

`<label>` is the ride folder name (e.g. `2026-05-01`) or `_test` in single-file test mode.

---

## Path A: Test one file (recommended first run)

Use this to tune thresholds before processing a full card of footage.

### Step 1: Pick a short raw MP4

Example: `E:\0. Moto Vids\raw\2026-05-01\GOPR0001.mp4`

### Step 2: Dry run (no files written)

See how many highlights would be detected:

```powershell
cd E:\REPOS\cjm-dev\scripts\video_editing

python clip_generator.py --test "E:\0. Moto Vids\raw\2026-05-01\GOPR0001.mp4" --dry-run --skip-splits
```

### Step 3: Generate test highlights (fast)

```powershell
python clip_generator.py --test "E:\0. Moto Vids\raw\2026-05-01\GOPR0001.mp4" --skip-splits --style pov
```

- Output: `highlights\_test\GOPR0001\`
- `--skip-splits` avoids writing 60-second segment files (saves time).

### Step 4: Review clips

Open the `highlights\_test\GOPR0001\` folder and watch `highlight_*.mp4`.

- Too many clips → raise `--motion` (e.g. `0.30`) or `--cooldown` (e.g. `22`).
- Too few → lower `--motion` (e.g. `0.18`) or `--audio-db` (e.g. `-22`).

### Step 5: Re-run with adjustments (optional)

```powershell
python clip_generator.py --test "E:\0. Moto Vids\raw\2026-05-01\GOPR0001.mp4" --skip-splits --motion 0.20 --audio-db -18 --cooldown 16
```

### Step 6: Vertical test (Reels / Shorts)

```powershell
python clip_generator.py --test "E:\0. Moto Vids\raw\2026-05-01\GOPR0001.mp4" --skip-splits --vertical
```

Files are named `highlight_000_9x16.mp4` (1080×1920 center crop).

---

## Path B: Process a full ride folder

### Step 1: Copy raw MP4s into a date folder

```text
E:\0. Moto Vids\raw\2026-05-01\
  GOPR0001.mp4
  GOPR0002.mp4
  ...
```

### Step 2: Choose camera style preset

| `--style` | Best for | Behavior |
|-----------|----------|----------|
| `pov` | Helmet / chest cam | More sensitive motion, shorter clips, shorter cooldown |
| `front` | Bike-mounted forward cam | Higher motion threshold, longer clips |
| `auto` | Default | Built-in defaults only (no preset override) |

### Step 3: Quick debug — first video only

```powershell
python clip_generator.py --folder 2026-05-01 --first-only --skip-splits --style pov
```

### Step 4: Full folder run

```powershell
python clip_generator.py --folder 2026-05-01 --style pov
```

This processes **every** `.mp4` in the folder and writes splits unless you pass `--skip-splits`.

### Step 5: Interactive folder pick (no `--folder`)

```powershell
python clip_generator.py --style pov
```

The script lists subfolders under `raw/` (newest first) and prompts for a number.

### Step 6: Check outputs

For each source file `GOPR0001.mp4`:

```text
highlights\2026-05-01\GOPR0001\
  highlight_000.mp4
  highlight_001.mp4
  metadata.json
splits\2026-05-01\GOPR0001\
  split_000.mp4
  ...
```

Open `metadata.json` to see timestamps and whether each clip aligned with an **audio acceleration** spike.

### Step 7: Re-run behavior

If a `highlight_NNN.mp4` already exists, that index is **skipped** (not overwritten). Delete specific clips or the whole output folder to regenerate.

---

## Path C: Different base directory

```powershell
python clip_generator.py --base-dir "D:\Moto Vids" --folder 2026-05-01
```

Or set `MOTO_VIDS_BASE` once per session (see [Setup](setup.md)).

---

## Detection logic (what to expect in logs)

1. **Motion** — FFmpeg `select='gt(scene,THRESHOLD)'` on a scaled-down stream; each cut adds a candidate timestamp.
2. **Audio** — RMS level above `--audio-db` (default -20 dBFS), minimum `--audio-db` gap between spikes.
3. **Merge** — Motion + audio candidates sorted, deduped with `--cooldown` seconds between starts, capped at `--max-highlights` (default 40).
4. **Export** — Each highlight starts `--lead-in` seconds before the peak and lasts `--highlight-duration` seconds (default 18s).

---

## Hand off to montage builder

1. Review highlights under `highlights\<date>\...`
2. Copy your favorite `.mp4` files into a theme pool:

```text
E:\0. Moto Vids\montage_pool\<theme_name>\
  clip_from_ride_a.mp4
  clip_from_ride_b.mp4
```

3. Optionally copy `metadata.json` fields — montage builder reads `metadata.json` in the **pool** folder if present (see [Montage builder](montage-builder.md)).

Or rename clips with timestamp suffixes; the montage script also parses timestamps from filenames.

---

## Troubleshooting

| Issue | What to try |
|-------|-------------|
| No highlights found | Lower `--motion` or `--audio-db`; check audio track exists |
| Too many similar clips | Raise `--cooldown` or `--motion` |
| FFmpeg not found | [Setup](setup.md) — PATH |
| Folder not found | Check `--base-dir` and `raw\<folder>` spelling |
| Very slow on long 4K files | Lower cost: `--skip-splits`, `--detect-width 640` |

Full flag list: [Reference](reference.md).
