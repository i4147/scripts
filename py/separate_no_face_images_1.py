
import shutil
from pathlib import Path
from multiprocessing import Pool, cpu_count
from functools import partial
from tqdm import tqdm

try:
    import cv2

    FACE_DETECTION_AVAILABLE = True
except ImportError:
    FACE_DETECTION_AVAILABLE = False
    print("Warning: OpenCV not installed. Install with: pip install opencv-python")


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}


def is_image_file(filepath: Path) -> bool:
    return filepath.suffix.lower() in IMAGE_EXTENSIONS


def has_human_face(image_path: Path, cascade_path: str = None) -> bool:
    if not FACE_DETECTION_AVAILABLE:
        return True

    if cascade_path is None:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"

    face_cascade = cv2.CascadeClassifier(cascade_path)

    
    image = cv2.imread(str(image_path))
    if image is None:
        return True  

    
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))

    return len(faces) > 0


def process_single_image(args) -> tuple:
    filepath, current_dir, no_face_dir = args

    try:
        
        has_face = has_human_face(filepath)

        if not has_face:
            
            relative_path = filepath.relative_to(current_dir)
            destination = no_face_dir / relative_path

            
            destination.parent.mkdir(parents=True, exist_ok=True)

            
            shutil.move(str(filepath), str(destination))
            return (filepath, destination, True, has_face)
        else:
            return (filepath, None, False, has_face)

    except Exception as e:
        print(f"  ❌ Error processing {filepath.name}: {e}")
        return (filepath, None, False, True)  


def collect_images(directory: Path, exclude_dir: Path) -> list:
    images = []

    for filepath in directory.rglob("*"):
        
        if exclude_dir in filepath.parents or filepath.parent == exclude_dir:
            continue

        if filepath.is_file() and is_image_file(filepath):
            images.append(filepath)

    return images


def folderize_images(num_workers: int = None):

    if not FACE_DETECTION_AVAILABLE:
        print("\n❌ OpenCV is required for face detection.")
        print("   Install it with: pip install opencv-python")
        print("   Also install tqdm: pip install tqdm\n")
        return

    current_dir = Path.cwd()
    no_face_dir = current_dir / "no_face"

    
    no_face_dir.mkdir(exist_ok=True)
    print(f"📁 Output directory: {no_face_dir}\n")

    
    print("🔍 Scanning for images...")
    images = collect_images(current_dir, no_face_dir)

    if not images:
        print("No images found!")
        return

    print(f"Found {len(images)} images")

    
    if num_workers is None:
        num_workers = min(cpu_count(), len(images))
    num_workers = max(1, num_workers)

    print(f"Using {num_workers} worker processes\n")

    
    args_list = [(img, current_dir, no_face_dir) for img in images]

    
    results = []
    process_func = partial(process_single_image)

    with Pool(processes=num_workers) as pool:
        
        for result in tqdm(
            pool.imap_unordered(process_single_image, args_list),
            total=len(images),
            desc="Processing images",
            unit="img",
            ncols=80,
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
        ):
            results.append(result)
            
            tqdm.write(f"  → {result[0].name}")

    
    total = len(results)
    moved = sum(1 for _, _, moved, _ in results if moved)
    no_face_count = sum(1 for _, _, _, has_face in results if not has_face)
    has_face_count = total - no_face_count

    
    print("\n" + "=" * 60)
    print("📊 SUMMARY")
    print("=" * 60)
    print(f"Total images processed: {total}")
    print(f"Images with faces: {has_face_count}")
    print(f"Images without faces: {no_face_count}")
    print(f"Images moved to 'no_face': {moved}")

    if moved > 0:
        print(f"\n📁 Moved images to: {no_face_dir}")

        
        moved_files = [(orig, dest) for orig, dest, moved, _ in results if moved][:5]
        if moved_files:
            print("\nSample of moved files:")
            for orig, dest in moved_files:
                print(f"  {orig.relative_to(current_dir)} → no_face/{dest.relative_to(no_face_dir)}")
            if moved > 5:
                print(f"  ... and {moved - 5} more")

    print("=" * 60)


if __name__ == "__main__":
    import sys

    print("🔍 Face Detection Image Organizer (Multiprocessing Version)")
    print("=" * 60)
    print(f"Working directory: {Path.cwd()}")
    print("Images with faces will stay in place")
    print("Images WITHOUT faces will be moved to 'no_face/'")
    print("=" * 60 + "\n")

    
    num_workers = None
    if len(sys.argv) > 1:
        try:
            num_workers = int(sys.argv[1])
            print(f"Using {num_workers} workers as specified\n")
        except ValueError:
            print("Usage: python script.py [num_workers]")
            sys.exit(1)

    response = input("Continue? (y/n): ").lower().strip()
    if response == "y":
        folderize_images(num_workers)
    else:
        print("Operation cancelled.")
