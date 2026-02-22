import os
import subprocess
import sys
import json

class MotoClipGenerator:
    def __init__(self):
        self.base_dir = r"E:\0. Moto Vids"

        self.raw_dir = os.path.join(self.base_dir, "raw")
        self.highlight_dir = os.path.join(self.base_dir, "highlights")
        self.split_dir = os.path.join(self.base_dir, "splits")

        # UPDATED SETTINGS
        self.highlight_duration = 20
        self.split_duration = 60
        self.motion_threshold = 0.3

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
    def detect_motion_timestamps(self, video_path):
        print(f"Detecting motion in {video_path} ...")

        command = [
            "ffmpeg",
            "-i", video_path,
            "-vf", f"select='gt(scene,{self.motion_threshold})',showinfo",
            "-f", "null",
            "-"
        ]

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        timestamps = []
        for line in process.stdout:
            if "pts_time:" in line:
                try:
                    t = float(line.split("pts_time:")[1].split()[0])
                    timestamps.append(t)
                except:
                    pass

        process.wait()
        return timestamps

    # --------------------------------------------------
    def create_highlight(self, video_path, timestamp, output_file):
        start = max(timestamp - 5, 0)

        command = [
            "ffmpeg",
            "-ss", str(start),
            "-i", video_path,
            "-t", str(self.highlight_duration),
            "-filter_complex",
            "[0:v]scale=1080:-2,boxblur=20:1[bg];"
            "[0:v]scale=-2:1080[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2",
            "-preset", "veryfast",
            "-crf", "18",
            output_file
        ]

        self.run_ffmpeg(command)

    # --------------------------------------------------
    def split_video(self, video_path, output_dir):
        self.ensure_dir(output_dir)

        command = [
            "ffmpeg",
            "-i", video_path,
            "-c", "copy",
            "-f", "segment",
            "-segment_time", str(self.split_duration),
            "-reset_timestamps", "1",
            os.path.join(output_dir, "split_%03d.mp4")
        ]

        self.run_ffmpeg(command)

    # --------------------------------------------------
    def process_video(self, video_file, date_folder):
        video_path = os.path.join(self.raw_dir, date_folder, video_file)
        video_name = os.path.splitext(video_file)[0]

        highlight_path = os.path.join(self.highlight_dir, date_folder, video_name)
        split_path = os.path.join(self.split_dir, date_folder, video_name)

        self.ensure_dir(highlight_path)
        self.ensure_dir(split_path)

        print(f"\nProcessing {video_file}")

        metadata = {
            "video": video_file,
            "highlights": []
        }

        timestamps = self.detect_motion_timestamps(video_path)

        for idx, t in enumerate(timestamps):
            output_file = os.path.join(highlight_path, f"highlight_{idx:03d}.mp4")

            if os.path.exists(output_file):
                continue

            self.create_highlight(video_path, t, output_file)

            metadata["highlights"].append({
                "file": output_file,
                "timestamp": t
            })

        self.split_video(video_path, split_path)

        metadata_file = os.path.join(highlight_path, "metadata.json")
        with open(metadata_file, "w") as f:
            json.dump(metadata, f, indent=4)

        print("Done.")

    # --------------------------------------------------
    def process_date_folder(self):
        date_folder = input("Enter date folder: ")
        raw_date_path = os.path.join(self.raw_dir, date_folder)

        if not os.path.exists(raw_date_path):
            print("Date folder not found.")
            return

        for file in os.listdir(raw_date_path):
            if file.lower().endswith(".mp4"):
                self.process_video(file, date_folder)


if __name__ == "__main__":
    generator = MotoClipGenerator()
    generator.process_date_folder()