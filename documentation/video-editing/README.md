# Video editing (motorcycle highlights & montages)

Step-by-step guides for extracting highlight clips from ride footage and building montage videos for posting.

## Workflow

```
Raw ride MP4s          clip_generator.py          montage_builder.py
─────────────────      ───────────────────        ──────────────────
raw/<date>/      →     highlights/<date>/...  →   (copy picks to pool)
                         splits/<date>/...          montage_pool/<theme>/
                                                    montages/<theme>/
```

1. **Clip generator** — detect motion + audio spikes, export short highlights (and optional splits).
2. **Montage builder** — concatenate pool clips into one or more montage files (landscape or 9:16).

## Guides

| Guide | Use when |
|-------|----------|
| [Setup](setup.md) | Install FFmpeg, folder layout, `MOTO_VIDS_BASE` |
| [Clip generator](clip-generator.md) | Extract highlights from raw ride footage |
| [Montage builder](montage-builder.md) | Build montages from a clip pool |
| [Reference](reference.md) | CLI flags, presets, metadata, troubleshooting |

## Quick commands

From the repo (or any directory — scripts use absolute paths for video roots):

```powershell
cd E:\REPOS\cjm-dev\scripts\video_editing
```

**Test one raw file**

```powershell
python clip_generator.py --test "E:\0. Moto Vids\raw\2026-05-01\GOPR0001.mp4" --skip-splits --first-only
```

**Process a full ride folder**

```powershell
python clip_generator.py --folder 2026-05-01 --style pov
```

**Build montages**

```powershell
python montage_builder.py --theme summer_rides --count 3 --shuffle
```

## Default folders

Unless you set `--base-dir` or `MOTO_VIDS_BASE`, the default root is `E:\0. Moto Vids`:

| Path | Purpose |
|------|---------|
| `raw/<date>/` | Source ride MP4s |
| `highlights/<date>/<video_stem>/` | Generated clips + `metadata.json` |
| `splits/<date>/<video_stem>/` | Optional 60s segments (copy, no re-encode) |
| `montage_pool/<theme>/` | Clips you chose for montages |
| `montages/<theme>/` | Finished montage MP4s |
