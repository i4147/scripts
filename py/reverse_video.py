import cv2
import sys
from concurrent.futures import ThreadPoolExecutor


def reverse_video_parallel(input_file, output_file="reversed.mp4", num_threads=8):
    cap = cv2.VideoCapture(input_file)

    if not cap.isOpened():
        print(f"Error: Could not open video file {input_file}")
        return

    
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"Video: {width}x{height}, {fps}fps, {total_frames} frames")

    
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    frames = []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
    cap.release()

    
    def process_chunk(chunk_indices):
        return [frames[i] for i in chunk_indices]

    
    chunk_size = max(1, total_frames // num_threads)
    chunks = []
    for i in range(0, total_frames, chunk_size):
        end = min(i + chunk_size, total_frames)
        
        indices = list(range(total_frames - 1 - end, total_frames - 1 - i, -1))
        chunks.append(indices)

    
    reversed_frames = []
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        results = executor.map(process_chunk, chunks)
        for result in results:
            reversed_frames.extend(result)

    
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_file, fourcc, fps, (width, height))

    for frame in reversed_frames:
        out.write(frame)

    out.release()
    print(f"Saved to {output_file}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python script.py <input_video_file>")
        sys.exit(1)

    reverse_video_parallel(sys.argv[1], num_threads=8)
