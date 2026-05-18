# Video editing reference

## Scripts

| File | Purpose |
|------|---------|
| `scripts/video_editing/clip_generator.py` | Motion + audio highlight extraction |
| `scripts/video_editing/montage_builder.py` | Concat montages from `montage_pool/` |
| `scripts/video_editing/deprecated/video_editor_engine.py` | Legacy monolith — **not** used by current workflow |

## Environment

| Variable | Default | Used by |
|----------|---------|---------|
| `MOTO_VIDS_BASE` | `E:\0. Moto Vids` | Both scripts (`--base-dir` overrides) |

## Folder map (under base dir)

```text
raw/<ride_folder>/*.mp4              # Input to clip_generator
highlights/<label>/<video_stem>/     # Output clips + metadata.json
splits/<label>/<video_stem>/         # Optional 60s segments (stream copy)
montage_pool/<theme>/*.mp4           # Input to montage_builder
montages/<theme>/*.mp4               # Output montages
```

---

## clip_generator.py — CLI

```text
python clip_generator.py [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--base-dir` | `MOTO_VIDS_BASE` or `E:\0. Moto Vids` | Root for raw/highlights/splits |
| `--folder` | (interactive) | Subfolder name under `raw/` |
| `--test VIDEO.mp4` | — | Single file → `highlights/_test/<stem>/` |
| `--first-only` | off | With `--folder`, process only first MP4 |
| `--skip-splits` | off | Do not write `splits/` segments |
| `--vertical` | off | 9:16 center crop; `_9x16` in filename |
| `--dry-run` | off | Log only; no FFmpeg output |
| `--style` | `auto` | `pov`, `front`, or `auto` |

### Style presets

| Preset | motion_threshold | highlight_duration | lead_in | cooldown |
|--------|------------------|--------------------|---------|----------|
| `pov` | 0.22 | 16s | 4s | 14s |
| `front` | 0.32 | 20s | 5s | 20s |
| `auto` | 0.25 | 18s | 5s | 18s |

### Tuning flags (override config)

| Flag | Config field | Default |
|------|--------------|---------|
| `--highlight-duration` | seconds per clip | 18 |
| `--lead-in` | start before peak | 5 |
| `--motion` | scene threshold 0–1 | 0.25 (or preset) |
| `--audio-db` | RMS dBFS spike threshold | -20 |
| `--cooldown` | min gap between highlights | 18 |
| `--max-highlights` | cap per source file | 40 |
| `--detect-width` | scale width for detection pass | 960 |
| `--crf` | libx264 quality | 18 |

### Encode defaults (highlights)

- Video: libx264, preset `veryfast`, CRF 18, yuv420p
- Audio: AAC 192k
- `+faststart` on MP4

---

## montage_builder.py — CLI

```text
python montage_builder.py [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--base-dir` | `MOTO_VIDS_BASE` or `E:\0. Moto Vids` | Root for pool/montages |
| `--theme` | (prompt) | Subfolder under `montage_pool/` |
| `--count` | 3 | Number of montages (`--test` forces 1) |
| `--max-length` | 120 | Max seconds per montage |
| `--vertical` | off | 1080×1920 pad; `_9x16` suffix |
| `--shuffle` | off | Random clip order per montage |
| `--test` | off | Single montage `*_montage_test.mp4` |
| `--crf` | 20 | libx264 CRF for montage output |

### Selection rules (code defaults)

| Setting | Value |
|---------|--------|
| `max_clip_usage` | 2 uses per clip per run |
| Landscape output | 1920×1080 scale + pad |
| Vertical output | 1080×1920 scale + pad |
| Min clips to continue multi-montage | 2 selected (non-test) |

### Clip priority (no `--shuffle`)

1. Clips with `acceleration: true` in pool `metadata.json` rank higher
2. Then by timestamp (metadata or filename)
3. Usage cap and `--max-length` applied when building each montage

---

## metadata.json (clip generator output)

Written to each highlight folder:

```json
{
  "video": "GOPR0001.mp4",
  "source_path": "...",
  "style": "pov",
  "vertical_export": false,
  "highlights": [
    {
      "file": "...\\highlight_000.mp4",
      "timestamp": 45.2,
      "acceleration": true
    }
  ]
}
```

Montage builder reads **pool-level** `metadata.json` keyed by **filename** (`Path(fp).name`).

---

## Keyboard interrupt

Both scripts catch **Ctrl+C**, terminate FFmpeg, and exit. Safe to abort long encodes.

---

## Common issues

| Symptom | Likely cause |
|---------|----------------|
| `ffmpeg` / `ffprobe` not recognized | FFmpeg not on PATH |
| Empty highlight folder | Thresholds too strict; no scene/audio peaks |
| Montage stops after first file | Pool too small for `--count` + `--max-length` |
| Dark or soft montage | Default CRF 20; use `--crf 18` |
| Clips look cropped wrong (vertical) | Generator crops center; montage pads — different algorithms |

---

## Related documentation

- [Setup](setup.md)
- [Clip generator walkthrough](clip-generator.md)
- [Montage builder walkthrough](montage-builder.md)
