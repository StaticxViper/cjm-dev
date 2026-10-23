# Video editing

`clip_generator.py` cuts highlight clips from raw footage with FFmpeg scene detection and audio spikes. `montage_builder.py` concatenates a themed pool of those clips into a montage. Both can export landscape or 9:16.

**Inputs:** a media root (`--base-dir` or `MOTO_VIDS_BASE`) with `raw/` footage for clips, and `montage_pool/{theme}/` for montages. **Outputs:** clip files plus metadata JSON, and montage files under `montages/`.

**Local run** from this directory (FFmpeg and ffprobe on `PATH`):

```bash
python clip_generator.py --folder 2026-01-01
python montage_builder.py --theme commute
```

**Script Manager:** `clip-generator` and `montage-builder`. No video-specific GitHub Actions workflow.

**Secrets:** none. Optional `MOTO_VIDS_BASE`.

Longer guides: [clip generator](../../documentation/scripts/clip_generator.md), [montage builder](../../documentation/scripts/montage_builder.md).
