import os
import subprocess
import random
import sys

class MotoContentFactory:
    def __init__(self):
        # Hardcoded base directory
        self.base_dir = r"E:\0. Moto Vids"

        # Folders
        self.raw_dir = os.path.join(self.base_dir, "raw")
        self.highlight_dir = os.path.join(self.base_dir, "highlights")
        self.split_dir = os.path.join(self.base_dir, "splits")
        self.montage_dir = os.path.join(self.base_dir, "montages")

        # Config
        self.highlight_duration = 30  # seconds
        self.split_duration = 120     # seconds
        self.motion_threshold = 0.3   # scene detection threshold
        self.montage_variations = 20  # how many montage combinations per ride

    # --------------------------------------------------
    # Utility
    # --------------------------------------------------
    def ensure_dir(self, path):
        os.makedirs(path, exist_ok=True)

    def run_ffmpeg(self, command):
        """Run FFmpeg and stream output in real-time for safe Ctrl+C"""
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
            print("\nUser interrupted. Terminating FFmpeg...")
            process.terminate()
            process.wait()
            sys.exit(1)
        process.wait()
        if process.returncode != 0:
            print(f"FFmpeg exited with code {process.returncode}")

    # --------------------------------------------------
    # Motion Detection (Scene Changes)
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
    # Highlight Creation (Vertical + Blur Background)
    # --------------------------------------------------
    def create_highlight(self, video_path, timestamp, output_file):
        start = max(timestamp - 5, 0)  # 5 seconds before scene change
        command = [
            "ffmpeg",
            "-ss", str(start),
            "-i", video_path,
            "-t", str(self.highlight_duration),
            "-filter_complex",
            "[0:v]scale=1080:-2,boxblur=20:1[bg];"
            "[0:v]scale=-2:1080[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2",
            "-preset", "fast",
            "-crf", "20",
            output_file
        ]
        self.run_ffmpeg(command)

    # --------------------------------------------------
    # Split Video into 1-2 min segments
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
    # Generate Multiple Montage Variations
    # --------------------------------------------------
    def generate_montages(self, clips, output_dir):
        self.ensure_dir(output_dir)
        montage_count = self.montage_variations
        if len(clips) < 3:
            print("Not enough clips to create montages.")
            return

        for i in range(montage_count):
            selected = random.sample(
                clips,
                random.randint(3, min(8, len(clips)))
            )
            list_file = os.path.join(output_dir, "temp.txt")
            with open(list_file, "w") as f:
                for clip in selected:
                    f.write(f"file '{clip}'\n")
            output_file = os.path.join(output_dir, f"montage_{i:02d}.mp4")
            command = [
                "ffmpeg",
                "-f", "concat",
                "-safe", "0",
                "-i", list_file,
                "-c", "copy",
                output_file
            ]
            self.run_ffmpeg(command)
            os.remove(list_file)

    # --------------------------------------------------
    # Process a Single Video
    # --------------------------------------------------
    def process_video(self, video_file, date_folder):
        video_path = os.path.join(self.raw_dir, date_folder, video_file)
        video_name = os.path.splitext(video_file)[0]

        highlight_path = os.path.join(self.highlight_dir, date_folder, video_name)
        split_path = os.path.join(self.split_dir, date_folder, video_name)
        montage_path = os.path.join(self.montage_dir, date_folder, video_name)

        self.ensure_dir(highlight_path)
        self.ensure_dir(split_path)
        self.ensure_dir(montage_path)

        print(f"\nProcessing {video_file} ...")

        # Generate highlights
        timestamps = self.detect_motion_timestamps(video_path)
        highlight_files = []
        for idx, t in enumerate(timestamps):
            output_file = os.path.join(highlight_path, f"highlight_{idx:03d}.mp4")
            self.create_highlight(video_path, t, output_file)
            highlight_files.append(output_file)

        # Split full video
        self.split_video(video_path, split_path)

        # Collect split clips
        split_clips = [os.path.join(split_path, f) for f in os.listdir(split_path) if f.endswith(".mp4")]

        # Combine highlights + splits for montage pool
        all_clips = highlight_files + split_clips

        # Generate multiple montage variations
        self.generate_montages(all_clips, montage_path)

    # --------------------------------------------------
    # Process a Date Folder
    # --------------------------------------------------
    def process_date_folder(self):
        date_folder = input("Enter date folder (ex: 7.24.2025): ")
        raw_date_path = os.path.join(self.raw_dir, date_folder)
        if not os.path.exists(raw_date_path):
            print("Date folder not found.")
            return

        for file in os.listdir(raw_date_path):
            if file.lower().endswith(".mp4"):
                self.process_video(file, date_folder)


# --------------------------------------------------
# MAIN
# --------------------------------------------------
if __name__ == "__main__":
    factory = MotoContentFactory()
    factory.process_date_folder()