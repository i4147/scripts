from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
try:
    import cv2

    USE_CV2 = True
    logger.info("Using OpenCV for image processing")
except ImportError:
    try:
        from PIL import Image, ImageEnhance, ImageFilter

        USE_CV2 = False
        logger.info("OpenCV not found, using Pillow for image processing")
    except ImportError:
        logger.error("Neither OpenCV nor Pillow found. Please install at least one.")
        sys.exit(1)
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".gif"}


def process_image_cv2(image_path: Path) -> bool:
    try:
        img = cv2.imread(str(image_path))
        if img is None:
            logger.error(f"Failed to read image: {image_path}")
            return False
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
        denoised = cv2.fastNlMeansDenoising(thresh, None, 10, 7, 21)
        cv2.imwrite(str(image_path), denoised)
        return True
    except Exception as e:
        logger.error(f"Error processing {image_path}: {e}")
        return False


def process_image_pil(image_path: Path) -> bool:
    try:
        with Image.open(image_path) as img:
            if img.mode != "L":
                img = img.convert("L")
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(2.0)
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(2.0)
            img = img.filter(ImageFilter.GaussianBlur(radius=0.5))
            threshold = 128
            img = img.point(lambda p: p > threshold and 255)
            img.save(str(image_path))
            return True
    except Exception as e:
        logger.error(f"Error processing {image_path}: {e}")
        return False


def process_image(image_path: Path) -> tuple[Path, bool]:
    logger.debug(f"Processing: {image_path}")
    if USE_CV2:
        success = process_image_cv2(image_path)
    else:
        success = process_image_pil(image_path)
    return (image_path, success)


def find_images(paths: list[Path], recursive: bool = False) -> list[Path]:
    image_files = []
    for path in paths:
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            image_files.append(path)
        elif path.is_dir():
            if recursive:
                for ext in IMAGE_EXTENSIONS:
                    image_files.extend(path.rglob(f"*{ext}"))
                    image_files.extend(path.rglob(f"*{ext.upper()}"))
            else:
                for ext in IMAGE_EXTENSIONS:
                    image_files.extend(path.glob(f"*{ext}"))
                    image_files.extend(path.glob(f"*{ext.upper()}"))
    seen = set()
    unique_files = []
    for f in image_files:
        if f not in seen:
            seen.add(f)
            unique_files.append(f)
    return unique_files


def process_images_parallel(image_files: list[Path], max_workers: int | None = None) -> dict:
    if not image_files:
        logger.warning("No image files found to process")
        return {"success": 0, "failed": 0}
    if max_workers is None:
        max_workers = min(cpu_count(), len(image_files))
    logger.info(f"Processing {len(image_files)} images using {max_workers} workers")
    results = {"success": 0, "failed": 0}
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_path = {executor.submit(process_image, path): path for path in image_files}
        for future in as_completed(future_to_path):
            path = future_to_path[future]
            try:
                _, success = future.result()
                if success:
                    results["success"] += 1
                    logger.info(f"✓ Processed: {path}")
                else:
                    results["failed"] += 1
                    logger.error(f"✗ Failed: {path}")
            except Exception as e:
                results["failed"] += 1
                logger.error(f"✗ Error processing {path}: {e}")
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Prepare images for Tesseract OCR (in-place processing)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\nExamples:\n  %(prog)s image1.png image2.jpg     # Process specific files\n  %(prog)s /path/to/folder           # Process images in folder\n  %(prog)s -r /path/to/folder        # Process images recursively\n  %(prog)s                           # Process all images in current directory\n  %(prog)s -r                        # Process all images recursively\n        ",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or folders to process (if empty, process current directory)",
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Process subdirectories recursively",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers (default: CPU count)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    if not args.paths:
        args.paths = [Path.cwd()]
        logger.info(f"No input specified, processing current directory: {Path.cwd()}")
    image_files = find_images(args.paths, args.recursive)
    if not image_files:
        logger.error("No supported image files found")
        logger.info(f"Supported extensions: {', '.join(IMAGE_EXTENSIONS)}")
        return 1
    logger.info(f"Found {len(image_files)} image(s) to process")
    results = process_images_parallel(image_files, args.workers)
    logger.info("=" * 40)
    logger.info("Processing complete:")
    logger.info(f"  ✓ Success: {results['success']}")
    logger.info(f"  ✗ Failed:  {results['failed']}")
    logger.info(f"  Total:     {len(image_files)}")
    return 0 if results["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
