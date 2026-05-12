"""
Build montage videos from a pool of highlight clips (motorcycle / action edits).

Re-encodes for uniform resolution and web-friendly defaults. Optional 9:16 for Reels.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass
class MontageConfig:
    base_dir: Path = Path(r"E:\0. Moto Vids")
    pool_subdir: str = "montage_pool"
    output_subdir: str = "montages"
    max_montage_length: float = 120.0
    max_clip_usage: int = 2
    target_width: int = 1920
    target_height: int = 1080
    vertical_width: int = 1080
    vertical_height: int = 1920
    video_crf: int = 20
    encode_preset: str = "veryfast"
    audio_bitrate: str = "192k"

    @property
    def pool_dir(self) -> Path:
        return self.base_dir / self.pool_subdir

    @property
    def output_dir(self) -> Path:
        return self.base_dir / self.output_subdir


class MotoMontageBuilder:
    def __init__(self, cfg: MontageConfig):
        self.cfg = cfg

    def ensure_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def run_ffmpeg(self, command: Sequence[str]) -> int:
        process = subprocess.Popen(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            assert process.stdout is not None
            for line in process.stdout:
                print(line, end="")
        except KeyboardInterrupt:
            process.terminate()
            process.wait()
            sys.exit(1)
        process.wait()
        return process.returncode or 0

    def get_clip_duration(self, clip_path: Path) -> float:
        command = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(clip_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        return float(result.stdout.strip())

    def load_metadata_scores(self, theme_path: Path) -> Dict[str, dict]:
        meta_path = theme_path / "metadata.json"
        if not meta_path.is_file():
            return {}
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        out: Dict[str, dict] = {}
        for h in data.get("highlights", []):
            fp = h.get("file")
            if fp:
                out[str(Path(fp).name)] = h
        return out

    def load_clips(self, theme_path: Path) -> List[Tuple[Path, float, int]]:
        scores = self.load_metadata_scores(theme_path)
        clips: List[Tuple[Path, float, int]] = []
        for file in sorted(theme_path.iterdir()):
            if file.suffix.lower() != ".mp4":
                continue
            name = file.name
            ts = 0.0
            parts = name.replace(".mp4", "").split("_")
            try:
                ts = float(parts[-1])
            except ValueError:
                pass
            meta = scores.get(name, {})
            accel = 1 if meta.get("acceleration") else 0
            mts = meta.get("timestamp")
            if isinstance(mts, (int, float)):
                ts = float(mts)
            prio = accel * 1_000_000 - ts
            clips.append((file, ts, prio))
        clips.sort(key=lambda x: (-x[2], x[1]))
        return clips

    def build_montage_selection(
        self,
        sorted_clips: List[Tuple[Path, float, int]],
        usage_tracker: Dict[Path, int],
        *,
        max_length: float,
        shuffle: bool,
    ) -> List[Path]:
        pool = list(sorted_clips)
        if shuffle:
            random.shuffle(pool)
        total_length = 0.0
        selected: List[Path] = []
        for clip_path, _ts, _prio in pool:
            if usage_tracker.get(clip_path, 0) >= self.cfg.max_clip_usage:
                continue
            try:
                duration = self.get_clip_duration(clip_path)
            except (ValueError, subprocess.SubprocessError, OSError):
                continue
            if total_length + duration > max_length:
                continue
            selected.append(clip_path)
            total_length += duration
            usage_tracker[clip_path] = usage_tracker.get(clip_path, 0) + 1
        return selected

    def _scale_pad_filter(self, vertical: bool) -> str:
        if vertical:
            w, h = self.cfg.vertical_width, self.cfg.vertical_height
        else:
            w, h = self.cfg.target_width, self.cfg.target_height
        return (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
            f"setsar=1"
        )

    def create_montage(
        self,
        selected_clips: List[Path],
        output_path: Path,
        *,
        vertical: bool,
    ) -> None:
        if len(selected_clips) < 1:
            print("No clips to concatenate.")
            return
        self.ensure_dir(output_path.parent)
        list_file = output_path.parent / "_temp_concat_list.txt"
        vf = self._scale_pad_filter(vertical)
        with open(list_file, "w", encoding="utf-8") as f:
            for clip in selected_clips:
                ap = clip.resolve().as_posix().replace("'", "'\\''")
                f.write(f"file '{ap}'\n")
        command = [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            self.cfg.encode_preset,
            "-crf",
            str(self.cfg.video_crf),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            self.cfg.audio_bitrate,
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        self.run_ffmpeg(command)
        try:
            list_file.unlink()
        except OSError:
            pass

    def build_montages(
        self,
        theme: str,
        montage_count: int,
        *,
        max_length: float,
        vertical: bool,
        shuffle: bool,
        test_single: bool,
    ) -> None:
        theme_path = self.cfg.pool_dir / theme
        if not theme_path.is_dir():
            print(f"Theme folder not found: {theme_path}")
            return

        output_theme_dir = self.cfg.output_dir / theme
        self.ensure_dir(output_theme_dir)

        sorted_clips = self.load_clips(theme_path)
        if len(sorted_clips) < 1:
            print("No MP4 clips in pool folder.")
            return

        usage_tracker: Dict[Path, int] = {}
        count = 1 if test_single else montage_count

        for i in range(count):
            selected = self.build_montage_selection(
                sorted_clips,
                usage_tracker,
                max_length=max_length,
                shuffle=shuffle,
            )
            if len(selected) < 1:
                print("No clips selected.")
                break
            if not test_single and len(selected) < 2:
                print("Not enough remaining clips to continue.")
                break

            suffix = "_9x16" if vertical else ""
            tag = "test" if test_single else f"{i:02d}"
            output_file = output_theme_dir / f"{theme}_montage_{tag}{suffix}.mp4"

            print(f"\nCreating montage -> {output_file.name} ({len(selected)} clips)")
            self.create_montage(selected, output_file, vertical=vertical)

            if test_single:
                print("\n[Test mode] wrote single montage.")
                break

        print("\nDone.")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Motorcycle montage builder: concat pool clips, re-encode for posting."
    )
    p.add_argument(
        "--base-dir",
        type=Path,
        default=Path(os.environ.get("MOTO_VIDS_BASE", r"E:\0. Moto Vids")),
        help="Root (montage_pool/, montages/). Env MOTO_VIDS_BASE overrides.",
    )
    p.add_argument(
        "--theme",
        type=str,
        default="",
        help="Subfolder under montage_pool/ (non-interactive).",
    )
    p.add_argument(
        "--count",
        type=int,
        default=3,
        help="Number of montage files to build (ignored with --test).",
    )
    p.add_argument(
        "--max-length",
        type=float,
        default=120.0,
        help="Target max total duration in seconds per montage.",
    )
    p.add_argument(
        "--vertical",
        action="store_true",
        help="Output 9:16 padded (short-form).",
    )
    p.add_argument(
        "--shuffle",
        action="store_true",
        help="Randomize clip order when filling each montage.",
    )
    p.add_argument(
        "--test",
        action="store_true",
        help="Build exactly one montage (debug).",
    )
    p.add_argument("--crf", type=int, help="libx264 CRF (default 20).")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cfg = MontageConfig(base_dir=args.base_dir.expanduser().resolve())
    if args.crf is not None:
        cfg.video_crf = args.crf

    builder = MotoMontageBuilder(cfg)

    theme = args.theme.strip()
    if not theme:
        theme = input("Enter theme folder: ").strip()
    if not theme:
        print("Theme name required.")
        return

    montage_count = args.count
    if args.test:
        montage_count = 1
    elif not args.theme:
        try:
            montage_count = int(input("How many montages?: ").strip())
        except ValueError:
            montage_count = 3

    builder.build_montages(
        theme,
        montage_count,
        max_length=args.max_length,
        vertical=args.vertical,
        shuffle=args.shuffle,
        test_single=args.test,
    )


if __name__ == "__main__":
    main()
