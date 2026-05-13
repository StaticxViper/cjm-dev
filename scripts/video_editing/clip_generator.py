"""
Extract highlight clips from raw motorcycle ride footage (POV or front-facing).

Uses FFmpeg scene detection + audio RMS spikes. Supports test mode on a single file
and optional vertical (9:16) exports for short-form posting.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple


@dataclass
class ClipGeneratorConfig:
    base_dir: Path = Path(r"E:\0. Moto Vids")
    highlight_duration: float = 18.0
    split_duration: float = 60.0
    lead_in_seconds: float = 5.0
    motion_threshold: float = 0.25
    audio_rms_threshold_db: float = -20.0
    audio_spike_min_gap: float = 3.0
    highlight_cooldown: float = 18.0
    max_highlights_per_video: int = 40
    detect_scale_width: int = 960
    video_crf: int = 18
    encode_preset: str = "veryfast"
    audio_bitrate: str = "192k"
    vertical_width: int = 1080
    vertical_height: int = 1920

    @property
    def raw_dir(self) -> Path:
        return self.base_dir / "raw"

    @property
    def highlight_dir(self) -> Path:
        return self.base_dir / "highlights"

    @property
    def split_dir(self) -> Path:
        return self.base_dir / "splits"


STYLE_PRESETS: dict[str, dict[str, float]] = {
    "pov": {
        "motion_threshold": 0.22,
        "highlight_duration": 16.0,
        "lead_in_seconds": 4.0,
        "highlight_cooldown": 14.0,
    },
    "front": {
        "motion_threshold": 0.32,
        "highlight_duration": 20.0,
        "lead_in_seconds": 5.0,
        "highlight_cooldown": 20.0,
    },
    "auto": {},
}


class MotoClipGenerator:
    def __init__(self, cfg: ClipGeneratorConfig):
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
            print("\nInterrupted. Killing FFmpeg...")
            process.terminate()
            process.wait()
            sys.exit(1)
        process.wait()
        return process.returncode or 0

    def ffprobe_duration(self, video_path: Path) -> Optional[float]:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        try:
            return float(r.stdout.strip())
        except ValueError:
            return None

    def detect_motion_timestamps(self, video_path: Path) -> List[float]:
        print(f"Detecting motion (scene cuts) in {video_path} ...")
        w = max(320, min(self.cfg.detect_scale_width, 1920))
        vf = (
            f"scale={w}:-2,"
            f"select='gt(scene\\,{self.cfg.motion_threshold})',"
            f"showinfo"
        )
        command = [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(video_path),
            "-vf",
            vf,
            "-an",
            "-f",
            "null",
            "-",
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        timestamps: List[float] = []
        assert process.stdout is not None
        for line in process.stdout:
            if "pts_time:" in line:
                try:
                    t = float(line.split("pts_time:")[1].split()[0])
                    timestamps.append(t)
                except (IndexError, ValueError):
                    pass
        process.wait()
        return timestamps

    def detect_acceleration(self, video_path: Path) -> List[float]:
        print(f"Detecting audio spikes (revs / acceleration cues) in {video_path} ...")
        command = [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(video_path),
            "-af",
            "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level",
            "-f",
            "null",
            "-",
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        accel: List[float] = []
        last_time = -1e9
        assert process.stdout is not None
        for line in process.stdout:
            if "pts_time:" in line and "lavfi.astats.Overall.RMS_level=" in line:
                try:
                    t = float(line.split("pts_time:")[1].split()[0])
                    rms = float(
                        line.split("lavfi.astats.Overall.RMS_level=")[1].split()[0]
                    )
                    if rms > self.cfg.audio_rms_threshold_db:
                        if t - last_time >= self.cfg.audio_spike_min_gap:
                            accel.append(t)
                            last_time = t
                except (IndexError, ValueError):
                    pass
        process.wait()
        return accel

    def _video_filter_chain(self, vertical: bool) -> Optional[str]:
        if not vertical:
            return None
        vw, vh = self.cfg.vertical_width, self.cfg.vertical_height
        return (
            f"scale={vw}:{vh}:force_original_aspect_ratio=increase,"
            f"crop={vw}:{vh}"
        )

    def create_highlight(
        self,
        video_path: Path,
        timestamp: float,
        output_file: Path,
        *,
        vertical: bool,
        dry_run: bool,
    ) -> None:
        start = max(timestamp - self.cfg.lead_in_seconds, 0.0)
        vf = self._video_filter_chain(vertical)
        cmd: List[str] = [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-ss",
            str(start),
            "-i",
            str(video_path),
            "-t",
            str(self.cfg.highlight_duration),
            "-movflags",
            "+faststart",
        ]
        if vf:
            cmd += ["-vf", vf]
        cmd += [
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
            str(output_file),
        ]
        if dry_run:
            print(f"[dry-run] would write {output_file} from t={start:.2f}s")
            return
        self.ensure_dir(output_file.parent)
        self.run_ffmpeg(cmd)

    def split_video(self, video_path: Path, output_dir: Path) -> None:
        self.ensure_dir(output_dir)
        command = [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(video_path),
            "-c",
            "copy",
            "-f",
            "segment",
            "-segment_time",
            str(self.cfg.split_duration),
            "-reset_timestamps",
            "1",
            str(output_dir / "split_%03d.mp4"),
        ]
        self.run_ffmpeg(command)

    def merge_timestamp_candidates(
        self,
        motion: Iterable[float],
        accel: Iterable[float],
        duration: Optional[float],
    ) -> List[float]:
        all_ts = sorted(list(motion) + list(accel))
        cleaned: List[float] = []
        min_gap = self.cfg.highlight_cooldown
        for t in all_ts:
            if duration is not None and t >= duration - 2.0:
                continue
            if not cleaned:
                cleaned.append(t)
            elif t - cleaned[-1] > min_gap:
                cleaned.append(t)
        return cleaned[: self.cfg.max_highlights_per_video]

    def process_video(
        self,
        video_path: Path,
        *,
        relative_label: str,
        skip_splits: bool,
        vertical: bool,
        dry_run: bool,
    ) -> dict:
        video_name = video_path.stem
        highlight_path = self.cfg.highlight_dir / relative_label / video_name
        split_path = self.cfg.split_dir / relative_label / video_name
        self.ensure_dir(highlight_path)
        self.ensure_dir(split_path)

        print(f"\nProcessing {video_path.name}")

        duration = self.ffprobe_duration(video_path)
        if duration:
            print(f"Duration: {duration:.1f}s")

        motion_timestamps = self.detect_motion_timestamps(video_path)
        accel_timestamps = self.detect_acceleration(video_path)
        accel_set = set(accel_timestamps)
        cleaned = self.merge_timestamp_candidates(
            motion_timestamps, accel_timestamps, duration
        )
        print(
            f"Candidates: motion={len(motion_timestamps)} audio_spikes={len(accel_timestamps)} "
            f"-> {len(cleaned)} highlight(s) after cooldown/max cap"
        )

        metadata: dict = {
            "video": video_path.name,
            "source_path": str(video_path),
            "style": getattr(self.cfg, "_style_label", "custom"),
            "vertical_export": vertical,
            "highlights": [],
        }

        for idx, t in enumerate(cleaned):
            suffix = "_9x16" if vertical else ""
            output_file = highlight_path / f"highlight_{idx:03d}{suffix}.mp4"
            if output_file.exists() and not dry_run:
                print(f"Skip existing {output_file.name}")
                metadata["highlights"].append(
                    {
                        "file": str(output_file),
                        "timestamp": t,
                        "acceleration": any(abs(t - a) < 1.0 for a in accel_set),
                    }
                )
                continue

            self.create_highlight(
                video_path, t, output_file, vertical=vertical, dry_run=dry_run
            )

            metadata["highlights"].append(
                {
                    "file": str(output_file),
                    "timestamp": t,
                    "acceleration": any(abs(t - a) < 1.0 for a in accel_set),
                }
            )

        if not skip_splits and not dry_run:
            self.split_video(video_path, split_path)

        metadata_file = highlight_path / "metadata.json"
        if not dry_run:
            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)
            print(f"Wrote {metadata_file}")

        print("Done.")
        return metadata

    def process_date_folder(
        self,
        date_folder: str,
        *,
        only_first: bool,
        skip_splits: bool,
        vertical: bool,
        dry_run: bool,
    ) -> None:
        raw_date_path = self.cfg.raw_dir / date_folder
        if not raw_date_path.is_dir():
            print(f"Folder not found: {raw_date_path}")
            return

        video_files = sorted(
            [p for p in raw_date_path.iterdir() if p.suffix.lower() == ".mp4"]
        )
        if not video_files:
            print(f"No MP4 files in {raw_date_path}")
            return

        total = len(video_files)
        if only_first:
            video_files = video_files[:1]
            print(f"\n[test / first-only] Processing 1 of {total} videos\n")

        for idx, path in enumerate(video_files, 1):
            print(f"\nVideo {idx}/{len(video_files)}: {path.name}")
            print("-" * 60)
            self.process_video(
                path,
                relative_label=date_folder,
                skip_splits=skip_splits,
                vertical=vertical,
                dry_run=dry_run,
            )

        print("\nAll selected videos processed.\n")

    def interactive_pick_folder(self) -> Optional[str]:
        folders = sorted(
            [p.name for p in self.cfg.raw_dir.iterdir() if p.is_dir()],
            key=lambda f: (self.cfg.raw_dir / f).stat().st_mtime,
            reverse=True,
        )
        if not folders:
            print(f"No folders found in {self.cfg.raw_dir}")
            return None

        print("\nAvailable Ride Folders (Newest First):\n")
        for i, folder in enumerate(folders, 1):
            mtime = datetime.fromtimestamp((self.cfg.raw_dir / folder).stat().st_mtime)
            print(f"{i}. {folder}  |  Last Modified: {mtime}")

        while True:
            try:
                choice = int(input("\nSelect folder number: "))
                if 1 <= choice <= len(folders):
                    return folders[choice - 1]
                print("Invalid selection.")
            except ValueError:
                print("Enter a valid number.")

    def process_single_test_file(
        self,
        video_path: Path,
        *,
        skip_splits: bool,
        vertical: bool,
        dry_run: bool,
    ) -> None:
        video_path = video_path.resolve()
        if not video_path.is_file():
            print(f"Not a file: {video_path}")
            return
        label = "_test"
        print(f"\n[TEST MODE] Single file -> highlights under '{label}/'\n")
        self.process_video(
            video_path,
            relative_label=label,
            skip_splits=skip_splits,
            vertical=vertical,
            dry_run=dry_run,
        )


def apply_style(cfg: ClipGeneratorConfig, style: str) -> None:
    style = style.lower()
    if style not in STYLE_PRESETS:
        raise SystemExit(f"Unknown --style {style}; use pov, front, or auto")
    preset = STYLE_PRESETS[style]
    for k, v in preset.items():
        setattr(cfg, k, v)
    setattr(cfg, "_style_label", style)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Motorcycle clip generator: scene + audio spike highlights, optional 9:16."
    )
    p.add_argument(
        "--base-dir",
        type=Path,
        default=Path(os.environ.get("MOTO_VIDS_BASE", r"E:\0. Moto Vids")),
        help="Root folder (raw/, highlights/, splits/). Override with MOTO_VIDS_BASE env.",
    )
    p.add_argument(
        "--folder",
        type=str,
        default="",
        help="Date/raw subfolder name under raw/ (skips interactive pick if set).",
    )
    p.add_argument(
        "--test",
        type=Path,
        metavar="VIDEO.mp4",
        help="Process only this one file; outputs under highlights/_test/<stem>/.",
    )
    p.add_argument(
        "--first-only",
        action="store_true",
        help="With --folder, only process the first MP4 (quick debug).",
    )
    p.add_argument(
        "--skip-splits",
        action="store_true",
        help="Do not write segment splits (faster for testing).",
    )
    p.add_argument(
        "--vertical",
        action="store_true",
        help="Export 9:16 center-crop (short-form ready).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions only; no FFmpeg output files.",
    )
    p.add_argument(
        "--style",
        choices=("pov", "front", "auto"),
        default="auto",
        help="pov=more scene cuts/shorter clips; front=calmer threshold/longer clips; auto=no preset.",
    )
    p.add_argument("--highlight-duration", type=float, help="Seconds per clip.")
    p.add_argument("--lead-in", type=float, help="Seconds before peak to start each highlight.")
    p.add_argument("--motion", type=float, help="Scene detect threshold 0..1 (lower = more cuts).")
    p.add_argument("--audio-db", type=float, help="RMS dBFS threshold (e.g. -18 louder than -22).")
    p.add_argument("--cooldown", type=float, help="Min seconds between highlight start times.")
    p.add_argument("--max-highlights", type=int, help="Cap number of clips per source file.")
    p.add_argument("--detect-width", type=int, help="Scale width for detection pass only (default 960).")
    p.add_argument("--crf", type=int, help="libx264 CRF (default 18).")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cfg = ClipGeneratorConfig(base_dir=args.base_dir.expanduser().resolve())
    if args.style != "auto":
        apply_style(cfg, args.style)
    if args.highlight_duration is not None:
        cfg.highlight_duration = args.highlight_duration
    if args.lead_in is not None:
        cfg.lead_in_seconds = args.lead_in
    if args.motion is not None:
        cfg.motion_threshold = args.motion
    if args.audio_db is not None:
        cfg.audio_rms_threshold_db = args.audio_db
    if args.cooldown is not None:
        cfg.highlight_cooldown = args.cooldown
    if args.max_highlights is not None:
        cfg.max_highlights_per_video = args.max_highlights
    if args.detect_width is not None:
        cfg.detect_scale_width = args.detect_width
    if args.crf is not None:
        cfg.video_crf = args.crf
    setattr(cfg, "_style_label", getattr(cfg, "_style_label", args.style))

    gen = MotoClipGenerator(cfg)

    if args.test:
        gen.process_single_test_file(
            args.test,
            skip_splits=args.skip_splits,
            vertical=args.vertical,
            dry_run=args.dry_run,
        )
        return

    folder = args.folder.strip()
    if not folder:
        picked = gen.interactive_pick_folder()
        if not picked:
            return
        folder = picked

    gen.process_date_folder(
        folder,
        only_first=args.first_only,
        skip_splits=args.skip_splits,
        vertical=args.vertical,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
