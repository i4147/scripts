import multiprocessing
import sys
from functools import partial
import cv2
import numpy as np
import pytesseract


def _ocr_worker(frame_data, ocr_config):
    time_pos, subtitle_region = frame_data
    try:
        gray = cv2.cvtColor(subtitle_region, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        text = pytesseract.image_to_string(binary, config=ocr_config).strip()
        print(text)
        return time_pos, text
    except Exception:
        return time_pos, ""


def _frames_are_similar(a, b, threshold=0.97):
    small_a = cv2.resize(a, (64, 32))
    small_b = cv2.resize(b, (64, 32))
    diff = cv2.absdiff(small_a, small_b)
    similarity = 1.0 - diff.sum() / (diff.size * 255.0)
    return similarity >= threshold


def extract_frames(video_path, sample_fps=2.0, subtitle_top_ratio=0.75):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise OSError(f"Cannot open video: {video_path}")
    native_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_interval = max(1, int(native_fps / sample_fps))
    frames = []
    prev_region = None
    frame_count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_count % frame_interval == 0:
            h = frame.shape[0]
            region = frame[int(h * subtitle_top_ratio) :].copy()
            if prev_region is None or not _frames_are_similar(prev_region, region):
                frames.append((frame_count / native_fps, region))
                prev_region = region
        frame_count += 1
        print(frame_count)
    cap.release()
    return frames


def _merge_subtitles(subtitles, gap_threshold=1.0):
    if not subtitles:
        return []
    merged = []
    cur = dict(subtitles[0])
    for sub in subtitles[1:]:
        same_text = sub["text"] == cur["text"]
        close_enough = sub["start"] - cur["end"] <= gap_threshold
        if same_text and close_enough:
            cur["end"] = sub["end"]
        else:
            merged.append(cur)
            cur = dict(sub)
    merged.append(cur)
    return merged


def extract_burned_subs_ocr(
    video_path,
    output_srt_path,
    lang="fas",
    sample_fps=2.0,
    workers=None,
):
    if workers is None:
        workers = max(1, multiprocessing.cpu_count() - 1)
    print(f"[1/3] Extracting frames  ({sample_fps} fps sample)…")
    frames = extract_frames(video_path, sample_fps=sample_fps)
    print(f"      {len(frames)} unique frames queued for OCR")
    ocr_config = f"--oem 3 --psm 6 -l {lang}"
    worker_fn = partial(_ocr_worker, ocr_config=ocr_config)
    print(f"[2/3] Running OCR with {workers} worker(s)…")
    with multiprocessing.Pool(processes=4) as pool:
        results = pool.map(worker_fn, frames)
    subtitles = [{"start": t, "end": t + 1.0 / sample_fps, "text": txt} for t, txt in results if txt]
    subtitles.sort(key=lambda s: s["start"])
    subtitles = _merge_subtitles(subtitles)
    print(f"[3/3] Writing {len(subtitles)} subtitle(s) → {output_srt_path}")
    with open(output_srt_path, "w", encoding="utf-8") as f:
        for i, sub in enumerate(subtitles, 1):
            f.write(f"{i}\n")
            f.write(f"{format_time(sub['start'])} --> {format_time(sub['end'])}\n")
            f.write(f"{sub['text']}\n\n")
    print("Done.")


def format_time(seconds):
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds % 60
    ms = int((s - int(s)) * 400)
    return f"{h:02d}:{m:02d}:{int(s):02d},{ms:03d}"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python script.py &lt;video&gt; [output.srt] [sample_fps] [workers]")
        sys.exit(1)
    video = sys.argv[1]
    output = sys.argv[2] if len(sys.argv) > 2 else "extracted_subs.srt"
    fps_arg = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0
    worker_arg = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    extract_burned_subs_ocr(video, output, sample_fps=fps_arg, workers=worker_arg)
