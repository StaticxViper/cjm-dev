# Montage Builder

**Source:** `scripts/video_editing/montage_builder.py`

## Purpose

Builds re-encoded montage videos by concatenating highlight clips from a themed pool. Respects max duration per montage and per-clip usage limits. Supports landscape or 9:16 padded output for short-form posting.

## Prerequisites

- Python 3.12+
- **FFmpeg** and **ffprobe** on PATH
- Clips in `montage_pool/{theme}/` (typically produced by [clip_generator](clip_generator.md))

## Configuration

### Folder layout (under `--base-dir`)

```
{base-dir}/
  montage_pool/{theme}/   # Source clips (*.mp4)
  montages/               # Output montages
```

Default base: `E:\0. Moto Vids` or `MOTO_VIDS_BASE`.

Optional `metadata.json` from clip_generator informs clip usage tracking.

## How to run

```bash
cd scripts/video_editing
python montage_builder.py
```

Prompts for theme and montage count if not provided via flags.

### CLI flags

| Flag | Description |
|------|-------------|
| `--base-dir` | Root (`montage_pool/`, `montages/`) |
| `--theme` | Subfolder under `montage_pool/` |
| `--count` | Number of montages (default 3) |
| `--max-length` | Max seconds per montage (default 120) |
| `--vertical` | 9:16 padded output |
| `--shuffle` | Randomize clip order |
| `--test` | Build exactly one montage |
| `--crf` | libx264 CRF (default 20) |

## How it works

1. Resolve theme folder under `montage_pool/`.
2. Select clips respecting duration cap and usage limits.
3. Concatenate with FFmpeg re-encode.
4. Write montage files to `montages/`.

## Deprecated

See [clip_generator.md](clip_generator.md) — `video_editor_engine.py` in `deprecated/` is no longer maintained.

## Related scripts

- [clip_generator.md](clip_generator.md) — produces pool clips
