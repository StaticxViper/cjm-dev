# Clip Generator

**Source:** `scripts/video_editing/clip_generator.py`

## Purpose

Extracts highlight clips from motorcycle (or similar) raw footage using FFmpeg scene detection and audio RMS spike analysis. Supports landscape or 9:16 vertical export, optional segment splits, and per-style presets (`pov`, `front`, `auto`).

## Prerequisites

- Python 3.12+
- **FFmpeg** and **ffprobe** on PATH
- Optional: `MOTO_VIDS_BASE` env var for default media root

## Configuration

### Folder layout (under `--base-dir`)

```
{base-dir}/
  raw/{date-folder}/     # Source MP4s
  highlights/            # Generated clips
  splits/                # Optional segment splits
```

Default base: `E:\0. Moto Vids` or `MOTO_VIDS_BASE`.

Writes `metadata.json` per processed video.

## How to run

```bash
cd scripts/video_editing
python clip_generator.py
```

Interactive folder pick if `--folder` is omitted.

### CLI flags

| Flag | Description |
|------|-------------|
| `--base-dir` | Root folder (`raw/`, `highlights/`, `splits/`) |
| `--folder` | Subfolder under `raw/` (skips interactive pick) |
| `--test VIDEO.mp4` | Process one file under `highlights/_test/` |
| `--first-only` | With `--folder`, process only first MP4 |
| `--skip-splits` | Skip segment split outputs |
| `--vertical` | Export 9:16 center-crop |
| `--dry-run` | Print actions only |
| `--style` | `pov`, `front`, or `auto` |
| `--highlight-duration` | Seconds per clip |
| `--lead-in` | Seconds before peak to start clip |
| `--motion` | Scene detect threshold 0–1 |
| `--audio-db` | RMS dBFS threshold |
| `--cooldown` | Min seconds between highlights |
| `--max-highlights` | Cap clips per source file |
| `--detect-width` | Detection pass scale width |
| `--crf` | libx264 CRF (default 18) |

## How it works

1. Resolve config from CLI and optional style preset.
2. Pick a date folder under `raw/` (interactive or `--folder`).
3. For each MP4: run scene detection and audio analysis to find highlight windows.
4. Cut clips with FFmpeg; optionally write splits and vertical variants.
5. Save metadata JSON alongside outputs.

## Deprecated

`scripts/video_editing/deprecated/video_editor_engine.py` is superseded by this script and [montage_builder](montage_builder.md). Do not use for new workflows.

## Related scripts

- [montage_builder.md](montage_builder.md) — concatenates clips into montages
