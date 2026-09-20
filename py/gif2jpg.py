import sys
from pathlib import Path

import cv2
import numpy as np

THRESHOLD = 0.8


def hash_similarity(hash1: np.ndarray, hash2: np.ndarray) -> float:
    dist = cv2.norm(hash1, hash2, cv2.NORM_HAMMING)
    max_bits = hash1.size * 8
    return 1.0 - dist / max_bits


def gif_to_unique_jpg(gif_path: Path) -> None:
    if not gif_path.exists():
        raise FileNotFoundError(msg)
    if gif_path.suffix.lower() != ".gif":
        raise ValueError(msg)
    output_dir = gif_path.parent / gif_path.stem
    output_dir.mkdir(exist_ok=True)
    cap = cv2.VideoCapture(str(gif_path))
    if not cap.isOpened():
        raise RuntimeError(msg)
    hasher = cv2.img_hash.AverageHash_create()
    saved_count = 0
    frame_index = 0
    previous_hash = None
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        current_hash = hasher.compute(frame)
        save_frame = True
        if previous_hash is not None:
            similarity = hash_similarity(previous_hash, current_hash)
            if similarity >= THRESHOLD:
                save_frame = False
        if save_frame:
            output_file = output_dir / f"{gif_path.stem}_{saved_count:04d}.jpg"
            cv2.imwrite(str(output_file), frame)
            previous_hash = current_hash
            saved_count += 1
        frame_index += 1
    cap.release()
    print(f"✅ Saved {saved_count} unique frames to: {output_dir}")


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python gif_to_jpg_unique.py <input.gif>")
        sys.exit(1)
    gif_path = Path(sys.argv[1])
    gif_to_unique_jpg(gif_path)


if __name__ == "__main__":
    main()
