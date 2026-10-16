import argparse
import multiprocessing as mp
import sys
from pathlib import Path
import cv2
import numpy as np


def enhance_image(image_path: Path, output_dir: Path, verbose: bool = False) -> bool:
    try:
        if verbose:
            print(f"[PROCESSING] {image_path.name}...")
        img = cv2.imread(str(image_path))
        if img is None:
            print(f"[ERROR] Could not read: {image_path}")
            return False
        denoised = cv2.fastNlMeansDenoisingColored(img, None, 3, 3, 7, 21)
        lab = cv2.cvtColor(denoised, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        cl = clahe.apply(l_channel)
        enhanced_lab = cv2.merge((cl, a_channel, b_channel))
        color_corrected = cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)
        hsv = cv2.cvtColor(color_corrected, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)
        s = np.clip(s * 1.1, 0, 255).astype(np.uint8)
        enhanced_hsv = cv2.merge((h, s, v))
        vibrant_img = cv2.cvtColor(enhanced_hsv, cv2.COLOR_HSV2BGR)
        gaussian_blur = cv2.GaussianBlur(vibrant_img, (0, 0), 2.0)
        final_enhanced = cv2.addWeighted(vibrant_img, 1.5, gaussian_blur, -0.5, 0)
        output_path = output_dir / f"enhanced_{image_path.name}"
        cv2.imwrite(str(output_path), final_enhanced)
        if verbose:
            print(f"[SUCCESS] Saved enhanced version to: {output_path}")
        return True
    except Exception as e:
        print(f"[FAILED] Error processing {image_path.name}: {e}")
        return False


def collect_images(input_paths) -> list[Path]:
    valid_extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}
    images_to_process = []
    if not input_paths:
        print("[INFO] No inputs provided. Scanning current directory '.' recursively...")
        input_paths = [Path(".")]
    for path_str in input_paths:
        path = Path(path_str)
        if path.is_file() and path.suffix.lower() in valid_extensions:
            images_to_process.append(path)
        elif path.is_dir():
            for file in path.rglob("*"):
                if file.is_file() and file.suffix.lower() in valid_extensions:
                    if not file.name.startswith("enhanced_"):
                        images_to_process.append(file)
        else:
            print(f"[WARNING] Skipping invalid path or unsupported format: {path_str}")
    return list(set(images_to_process))


def main():
    parser = argparse.ArgumentParser(description="Multi-threaded Google Photos Style Auto-Enhancer")
    parser.add_argument("inputs", nargs="*", help="Files or folders to process. Defaults to recursive '.' if empty.")
    parser.add_argument("-o", "--output", default="enhanced_outputs", help="Folder to save enhanced pictures.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print details for every image processed.")
    args = parser.parse_args()
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    image_pool = collect_images(args.inputs)
    total_images = len(image_pool)
    if total_images == 0:
        print("[INFO] No supported images found to enhance. Exiting.")
        sys.exit(0)
    print(f"\n[START] Found {total_images} target images. Spawning parallel workers...")
    num_cores = mp.cpu_count()
    print(f"[SYSTEM] Utilizing {num_cores} parallel CPU threads.")
    tasks = [(img, output_dir, args.verbose) for img in image_pool]
    with mp.Pool(processes=num_cores) as pool:
        results = pool.starmap(enhance_image, tasks)
    successful_runs = sum(1 for r in results if r)
    print(f"\n[FINISHED] Done! Successfully enhanced {successful_runs}/{total_images} images.")
    print(f"[OUTPUT] Files are saved inside the folder: '{output_dir.resolve()}'")


if __name__ == "__main__":
    main()
