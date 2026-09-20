from __future__ import annotations

import argparse
import json
import os
import pickle
import signal
import sys
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

try:
    from ultralytics import YOLO

    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    print("Warning: YOLO not available. Install with: pip install ultralytics")
    print("Using basic nudity detection as fallback.")
try:
    import tensorflow as tf

    TF_AVAILABLE = True
except ImportError:
    TF_AVAILABLE = False


interrupted = False
checkpoint_data = None


def signal_handler(signum, frame):
    global interrupted
    interrupted = True
    print("\n\n⚠️  Interrupt received! Saving progress...")
    print("Press Ctrl+C again to force quit (may corrupt files)")


class ContentFilter:
    def __init__(self, threshold=0.5, use_nsfw_model=True):
        self.threshold = threshold
        self.use_nsfw_model = use_nsfw_model
        self.model = None
        self.nsfw_detector = None
        self._initialize_models()

    def _initialize_models(self):
        if YOLO_AVAILABLE:
            try:
                self.model = YOLO("yolov8n.pt")
                print("✓ YOLO model loaded")
            except Exception as e:
                print(f"⚠️  Could not load YOLO: {e}")
                self.model = None
        if self.use_nsfw_model:
            try:
                self._init_nsfw_detector()
            except Exception as e:
                print(f"⚠️  Could not initialize NSFW detector: {e}")
                print("Will use heuristic-based detection")

    def _init_nsfw_detector(self):
        self.skin_lower = np.array([0, 48, 80], dtype=np.uint8)
        self.skin_upper = np.array([20, 255, 255], dtype=np.uint8)

    def detect_inappropriate_content(self, frame):
        scores = []
        if self.model is not None:
            yolo_score = self._yolo_detection(frame)
            scores.append(yolo_score)
        skin_score = self._skin_detection(frame)
        scores.append(skin_score)
        texture_score = self._texture_analysis(frame)
        scores.append(texture_score)
        if scores:
            final_score = np.mean(scores)
            return final_score > self.threshold, final_score
        return False, 0.0

    def _yolo_detection(self, frame):
        try:
            results = self.model(frame, verbose=False)
            inappropriate_count = 0
            for r in results:
                boxes = r.boxes
                if boxes is not None:
                    for box in boxes:
                        cls = int(box.cls[0])
                        if cls == 0:
                            confidence = float(box.conf[0])
                            if confidence > 0.7:
                                inappropriate_count += 1
            frame_area = frame.shape[0] * frame.shape[1]
            score = min(inappropriate_count / 10, 1.0)
            return score
        except Exception as e:
            return 0.0

    def _skin_detection(self, frame):
        try:
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            skin_mask = cv2.inRange(hsv, self.skin_lower, self.skin_upper)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            skin_mask = cv2.morphologyEx(skin_mask, cv2.MORPH_OPEN, kernel)
            skin_mask = cv2.morphologyEx(skin_mask, cv2.MORPH_CLOSE, kernel)
            total_pixels = skin_mask.shape[0] * skin_mask.shape[1]
            skin_pixels = cv2.countNonZero(skin_mask)
            skin_ratio = skin_pixels / total_pixels
            score = min(skin_ratio * 3, 1.0)
            return score
        except Exception as e:
            return 0.0

    def _texture_analysis(self, frame):
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            edges = cv2.Canny(gray, 50, 150)
            edge_density = np.mean(edges) / 255
            score = max(0, 1 - edge_density * 2)
            return score
        except:
            return 0.0


class VideoProcessor:
    def __init__(self, input_path, output_clean="cleaned.mp4", output_flagged="plus16.mp4", threshold=0.5):
        self.input_path = input_path
        self.output_clean = output_clean
        self.output_flagged = output_flagged
        self.threshold = threshold
        self.filter = ContentFilter(threshold=threshold)
        self.cap = None
        self.writer_clean = None
        self.writer_flagged = None
        self.total_frames = 0
        self.processed_frames = 0
        self.flagged_frames = 0
        self.fps = 0
        self.frame_width = 0
        self.frame_height = 0
        self.checkpoint_file = f"{Path(input_path).stem}_checkpoint.json"

    def save_checkpoint(self, frame_number):
        checkpoint = {
            "input_path": self.input_path,
            "processed_frames": frame_number,
            "total_frames": self.total_frames,
            "flagged_frames": self.flagged_frames,
            "timestamp": datetime.now().isoformat(),
            "fps": self.fps,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
        }
        try:
            with open(self.checkpoint_file, "w") as f:
                json.dump(checkpoint, f, indent=2)
        except Exception as e:
            print(f"⚠️  Could not save checkpoint: {e}")

    def load_checkpoint(self):
        if os.path.exists(self.checkpoint_file):
            try:
                with open(self.checkpoint_file, "r") as f:
                    checkpoint = json.load(f)
                print(f"✓ Found checkpoint from {checkpoint['timestamp']}")
                print(f"  Progress: {checkpoint['processed_frames']}/{checkpoint['total_frames']} frames")
                return checkpoint
            except Exception as e:
                print(f"⚠️  Could not load checkpoint: {e}")
        return None

    def initialize_video(self):
        self.cap = cv2.VideoCapture(self.input_path)
        if not self.cap.isOpened():
            raise ValueError(f"Cannot open video: {self.input_path}")
        self.fps = int(self.cap.get(cv2.CAP_PROP_FPS))
        self.frame_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.frame_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        print(f"📹 Video: {self.input_path}")
        print(f"   Resolution: {self.frame_width}x{self.frame_height}")
        print(f"   FPS: {self.fps}")
        print(f"   Total frames: {self.total_frames}")

    def initialize_writers(self, append=False):
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        mode = "a" if append else "w"
        self.writer_clean = cv2.VideoWriter(self.output_clean, fourcc, self.fps, (self.frame_width, self.frame_height))
        self.writer_flagged = cv2.VideoWriter(
            self.output_flagged, fourcc, self.fps, (self.frame_width, self.frame_height)
        )

    def process_video(self, resume=False):
        checkpoint = None
        start_frame = 0
        if resume:
            checkpoint = self.load_checkpoint()
            if checkpoint:
                start_frame = checkpoint["processed_frames"]
                self.flagged_frames = checkpoint.get("flagged_frames", 0)
        self.initialize_video()
        self.initialize_writers(append=(start_frame > 0))
        if start_frame > 0:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
            print(f"⏩ Resuming from frame {start_frame}")
        signal.signal(signal.SIGINT, signal_handler)
        print(f"\n🎬 Processing video...")
        print(f"   Output clean: {self.output_clean}")
        print(f"   Output flagged: {self.output_flagged}")
        print(f"   Threshold: {self.threshold}")
        print("\n⏸️  Press Ctrl+C to pause and save progress\n")
        frame_buffer = deque(maxlen=5)
        frame_number = start_frame
        try:
            while True:
                ret, frame = self.cap.read()
                if not ret:
                    break
                if interrupted:
                    print(f"\n💾 Saving progress at frame {frame_number}...")
                    self.save_checkpoint(frame_number)
                    break
                frame_buffer.append(frame)
                is_inappropriate, confidence = self.filter.detect_inappropriate_content(frame)
                if is_inappropriate:
                    self.writer_flagged.write(frame)
                    self.flagged_frames += 1
                else:
                    self.writer_clean.write(frame)
                self.processed_frames += 1
                frame_number += 1
                if frame_number % 30 == 0:
                    progress = (frame_number / self.total_frames) * 100
                    flagged_pct = (self.flagged_frames / frame_number) * 100 if frame_number > 0 else 0
                    print(
                        f"\r⏳ Progress: {progress:.1f}% ({frame_number}/{self.total_frames}) "
                        f"| Flagged: {self.flagged_frames} ({flagged_pct:.1f}%) "
                        f"| Confidence: {confidence:.2f}",
                        end="",
                    )
                    if frame_number % 300 == 0:
                        self.save_checkpoint(frame_number)
        except Exception as e:
            print(f"\n❌ Error during processing: {e}")
            self.save_checkpoint(frame_number)
            raise
        finally:
            self.cleanup()
            if not interrupted:
                if os.path.exists(self.checkpoint_file):
                    os.remove(self.checkpoint_file)
        print(f"\n\n✅ Processing complete!")
        print(f"   Total frames processed: {self.processed_frames}")
        print(
            f"   Flagged frames: {self.flagged_frames} ({(self.flagged_frames / self.processed_frames * 100):.1f}%)"
            if self.processed_frames > 0
            else ""
        )
        print(f"   Clean video saved to: {self.output_clean}")
        print(f"   Flagged frames saved to: {self.output_flagged}")

    def cleanup(self):
        if self.cap is not None:
            self.cap.release()
        if self.writer_clean is not None:
            self.writer_clean.release()
        if self.writer_flagged is not None:
            self.writer_flagged.release()
        cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(
        description="Remove +16 content from videos with checkpoint/resume support",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:

  python video_filter.py input.mp4

  python video_filter.py input.mp4 -a

  python video_filter.py input.mp4 -a --resume

  python video_filter.py input.mp4 -a --threshold 0.7
        """,
    )
    parser.add_argument("input", help="Input video file path")
    parser.add_argument("-a", "--save-flagged", action="store_true", help="Save flagged frames to plus16.mp4")
    parser.add_argument("--threshold", type=float, default=0.5, help="Detection threshold (0.0-1.0, default: 0.5)")
    parser.add_argument("--resume", action="store_true", help="Resume from last checkpoint")
    parser.add_argument(
        "--output-clean", default="cleaned.mp4", help="Output filename for clean video (default: cleaned.mp4)"
    )
    parser.add_argument(
        "--output-flagged", default="plus16.mp4", help="Output filename for flagged frames (default: plus16.mp4)"
    )
    args = parser.parse_args()
    if not os.path.exists(args.input):
        print(f"❌ Error: Input file not found: {args.input}")
        sys.exit(1)
    if not 0 <= args.threshold <= 1:
        print("❌ Error: Threshold must be between 0.0 and 1.0")
        sys.exit(1)
    try:
        processor = VideoProcessor(
            input_path=args.input,
            output_clean=args.output_clean,
            output_flagged=args.output_flagged if args.save_flagged else None,
            threshold=args.threshold,
        )
        processor.process_video(resume=args.resume)
    except KeyboardInterrupt:
        print("\n\n⚠️  Processing interrupted by user")
        if "processor" in locals():
            processor.save_checkpoint(processor.processed_frames)
        print("Progress saved. Use --resume to continue later.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
