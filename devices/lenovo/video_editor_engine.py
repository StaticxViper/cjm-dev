import os
import subprocess as subp
from datetime import datetime

class VideoEditorEngine:
    def __init__(self, base_dir, segment_time=120, highlight_duration=20, luma_threshold=45.0):
        #Base folders
        self.base_dir = base_dir
        self.raw_dir = os.path.join(base_dir, "raw")
        self.split_dir = os.path.join(base_dir, "split")
        self.highlight_dir = os.path.join(base_dir, "highlights")
        self.montage_dir = os.path.join(base_dir, "montages")
        
        #Config
        self.segment_time = segment_time
        self.highlight_duration = highlight_duration
        self.luma_threshold = luma_threshold

    #Utility
    @staticmethod
    def ensure_folder(self):
        pass
        #print('ERROR WITH FOLDERS')
        #exit

    #FFmpeg Helpers
    def split_video(self, input_file, output_folder):
        self.ensure_folder(output_folder)
        command = [
            "ffmpeg",
            "-i", input_file,
            "-map", "0",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-c:a", "aac",
            "-f", "segment",
            "-segment_time", str(self.segment_time),
            "-reset_timestamps", "1",
            "-force_key_frames", f"expr:gte(t,n_forced*{self.segment_time})",
            os.path.join(output_folder, "split_%03d.mp4")
        ]
        subp.run(command)

    def detect_brightness(self, video_file):
        command = [
            "ffmpeg",
            "-i", video_file,
            "-vf", "signalstats",
            "-f", "null",
            "-"
        ]
        result = subp.run(command, capture_output=True, text=True)
        yavg_vals = []
        for line in result.stderr.splitlines():
            if "YAVG:" in line:
                try:
                    val = float(line.split("YAVG:")[1].split()[0])
                    yavg_vals.append(val)
                except:
                    pass
        if not yavg_vals:
            return None
        return sum(yavg_vals) / len(yavg_vals)

    def classify_day_night(self, avg_luma):
        return "NIGHT" if avg_luma < self.luma_threshold else "DAY"

    def create_highlight(self, segment_file, output_folder):
        self.ensure_folder(output_folder)
        basename = os.path.splitext(os.path.basename(segment_file))[0]
        output_file = os.path.join(output_folder, f"{basename}_highlight.mp4")
        command = [
            "ffmpeg",
            "-i", segment_file,
            "-ss", "0",
            "-t", str(self.highlight_duration),
            "-c", "copy",
            output_file
        ]
        subp.run(command)
        return output_file

    def create_montage(self, video_files, output_file):
        if not video_files:
            return
        list_file = "temp_list.txt"
        with open(list_file, "w") as f:
            for vf in video_files:
                f.write(f"file '{vf}'\n")
        command = [
            "ffmpeg",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            output_file
        ]
        subp.run(command)
        os.remove(list_file)

    #Main Processing
    def process_date_folder(self, date_folder):
        raw_date_path = os.path.join(self.raw_dir, date_folder)
        split_date_path = os.path.join(self.split_dir, date_folder)
        highlight_date_path = os.path.join(self.highlight_dir, date_folder)
        montage_date_path = os.path.join(self.montage_dir, date_folder)
        self.ensure_folder(montage_date_path)

        #Create ALL date folders
        os.makedirs(split_date_path, exist_ok=True)
        os.makedirs(highlight_date_path, exist_ok=True)
        os.makedirs(montage_date_path, exist_ok=True)

        all_split_videos = []
        all_highlight_videos = []

        for raw_file in os.listdir(raw_date_path):
            if raw_file.lower().endswith(".mp4"):
                raw_path = os.path.join(raw_date_path, raw_file)
                print(f"Processing {raw_file} ...")

                #1. Split video
                self.split_video(raw_path, split_date_path)

                #2. Brightness detection (first segment only)
                first_segment = os.path.join(split_date_path, "split_000.mp4")
                avg_luma = self.detect_brightness(first_segment)
                theme = self.classify_day_night(avg_luma) if avg_luma is not None else "DAY"
                print(f"Detected theme: {theme}")

                #3. Process split segments
                segments = [os.path.join(split_date_path, f) for f in os.listdir(split_date_path) if f.endswith(".mp4")]
                for seg in segments:
                    all_split_videos.append(seg)
                    highlight_file = self.create_highlight(seg, highlight_date_path)
                    all_highlight_videos.append(highlight_file)

        #4. Create montages
        montage_split_file = os.path.join(montage_date_path, f"{date_folder}_montage_splits.mp4")
        self.create_montage(all_split_videos, montage_split_file)

        montage_highlight_file = os.path.join(montage_date_path, f"{date_folder}_montage_highlights.mp4")
        self.create_montage(all_highlight_videos, montage_highlight_file)

    #Entry Point for All Dates
    def process_dates(self, folder_name):
        full_path = os.path.join(self.raw_dir, folder_name)
        if not os.path.exists(full_path):
            print("Folder not found.")
            return
        else:
            print(f"Processing date folder: {folder_name}")
            self.process_date_folder(folder_name)


if __name__ == "__main__":
    pipeline = VideoEditorEngine(base_dir=r"E:\0. Moto Vids")
    pipeline.process_dates('7.24.2025')
