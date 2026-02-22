import os
import subprocess
import random
import sys

class MotoMontageBuilder:
    def __init__(self):
        self.base_dir = r"E:\0. Moto Vids"

        self.pool_dir = os.path.join(self.base_dir, "montage_pool")
        self.output_dir = os.path.join(self.base_dir, "montages")

        # TARGET LENGTH SETTINGS
        self.max_montage_length = 30  # seconds
        self.min_clips = 2
        self.max_clips = 5

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
            print("\nInterrupted. Killing FFmpeg...")
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
    def build_structured_selection(self, clips):
        random.shuffle(clips)

        selected = []
        total_length = 0

        for clip in clips:
            duration = self.get_clip_duration(clip)

            if total_length + duration > self.max_montage_length:
                continue

            selected.append(clip)
            total_length += duration

            if len(selected) >= self.max_clips:
                break

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
        theme = input("Enter theme folder name (example: high_speed): ")
        theme_path = os.path.join(self.pool_dir, theme)

        if not os.path.exists(theme_path):
            print("Theme folder not found.")
            return

        montage_count = int(input("How many montages to generate?: "))

        output_theme_dir = os.path.join(self.output_dir, theme)
        self.ensure_dir(output_theme_dir)

        clips = [
            os.path.join(theme_path, f)
            for f in os.listdir(theme_path)
            if f.lower().endswith(".mp4")
        ]

        if len(clips) < self.min_clips:
            print("Not enough clips in theme folder.")
            return

        for i in range(montage_count):
            selected = self.build_structured_selection(clips.copy())

            if len(selected) < self.min_clips:
                print("Skipped montage — not enough fitting clips.")
                continue

            output_file = os.path.join(
                output_theme_dir,
                f"{theme}_montage_{i:02d}.mp4"
            )

            print(f"\nCreating montage {i+1}/{montage_count}")
            self.create_montage(selected, output_file)

        print("\nAll montages complete.")


if __name__ == "__main__":
    builder = MotoMontageBuilder()
    builder.build_montages()