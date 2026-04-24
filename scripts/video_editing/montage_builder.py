import os
import subprocess
import random
import json
import sys

class MotoMontageBuilder:
    def __init__(self):
        self.base_dir = r"E:\0. Moto Vids"

        self.pool_dir = os.path.join(self.base_dir, "montage_pool")
        self.output_dir = os.path.join(self.base_dir, "montages")

        self.max_montage_length = 30
        self.max_clip_usage = 2  # how many times a clip can be reused

    # --------------------------------------------------
    def ensure_dir(self, path):
        os.makedirs(path, exist_ok=True)

    def run_ffmpeg(self, command):
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        try:
            for line in process.stdout:
                print(line, end='')
        except KeyboardInterrupt:
            process.terminate()
            process.wait()
            sys.exit(1)
        process.wait()

    # --------------------------------------------------
    def get_clip_duration(self, clip_path):
        command = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            clip_path
        ]
        result = subprocess.run(command, stdout=subprocess.PIPE, text=True)
        return float(result.stdout.strip())

    # --------------------------------------------------
    def load_clips_with_timestamps(self, theme_path):
        clips = []

        for file in os.listdir(theme_path):
            if file.lower().endswith(".mp4"):
                path = os.path.join(theme_path, file)

                # Expect filenames like highlight_003_453.2.mp4 (timestamp embedded)
                parts = file.replace(".mp4", "").split("_")
                try:
                    timestamp = float(parts[-1])
                except:
                    timestamp = 0

                clips.append((path, timestamp))

        # Sort by timestamp
        clips.sort(key=lambda x: x[1])

        return clips

    # --------------------------------------------------
    def build_montage_selection(self, sorted_clips, usage_tracker):
        total_length = 0
        selected = []

        for clip_path, timestamp in sorted_clips:
            if usage_tracker.get(clip_path, 0) >= self.max_clip_usage:
                continue

            duration = self.get_clip_duration(clip_path)

            if total_length + duration > self.max_montage_length:
                break

            selected.append(clip_path)
            total_length += duration
            usage_tracker[clip_path] = usage_tracker.get(clip_path, 0) + 1

        return selected

    # --------------------------------------------------
    def create_montage(self, selected_clips, output_path):
        list_file = os.path.join(self.output_dir, "temp_concat.txt")

        with open(list_file, "w") as f:
            for clip in selected_clips:
                f.write(f"file '{clip}'\n")

        command = [
            "ffmpeg",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            output_path
        ]

        self.run_ffmpeg(command)
        os.remove(list_file)

    # --------------------------------------------------
    def build_montages(self):
        theme = input("Enter theme folder: ")
        theme_path = os.path.join(self.pool_dir, theme)

        if not os.path.exists(theme_path):
            print("Theme folder not found.")
            return

        montage_count = int(input("How many montages?: "))

        output_theme_dir = os.path.join(self.output_dir, theme)
        self.ensure_dir(output_theme_dir)

        sorted_clips = self.load_clips_with_timestamps(theme_path)
        usage_tracker = {}

        for i in range(montage_count):
            selected = self.build_montage_selection(sorted_clips, usage_tracker)

            if len(selected) < 2:
                print("Not enough remaining clips to continue.")
                break

            output_file = os.path.join(
                output_theme_dir,
                f"{theme}_montage_{i:02d}.mp4"
            )

            print(f"\nCreating montage {i+1}")
            self.create_montage(selected, output_file)

        print("\nDone.")


if __name__ == "__main__":
    builder = MotoMontageBuilder()
    builder.build_montages()