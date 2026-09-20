
import os
import shutil
from pathlib import Path

try:
    import cv2

    FACE_DETECTION_AVAILABLE = True
except ImportError:
    FACE_DETECTION_AVAILABLE = False
    print("Warning: OpenCV not installed. Install with: pip install opencv-python")


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}


def is_image_file(filename):
    return Path(filename).suffix.lower() in IMAGE_EXTENSIONS


def has_human_face(image_path, cascade_path=None):
    if not FACE_DETECTION_AVAILABLE:
        return True  

    
    if cascade_path is None:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"

    face_cascade = cv2.CascadeClassifier(cascade_path)

    
    image = cv2.imread(str(image_path))
    if image is None:
        print(f"  Warning: Could not read image {image_path}")
        return True  

    
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))

    return len(faces) > 0


def folderize_images():

    if not FACE_DETECTION_AVAILABLE:
        print("\n❌ OpenCV is required for face detection.")
        print("   Install it with: pip install opencv-python")
        print("\n   Alternatively, use a custom cascade file.\n")
        return

    current_dir = Path.cwd()
    no_face_dir = current_dir / "no_face"

    
    no_face_dir.mkdir(exist_ok=True)
    print(f"📁 Created/Using directory: {no_face_dir}\n")

    
    image_count = 0
    no_face_count = 0
    moved_count = 0

    for root, dirs, files in os.walk(current_dir):
        root_path = Path(root)

        
        if root_path == no_face_dir:
            continue

        for file in files:
            file_path = root_path / file

            if not is_image_file(file):
                continue

            image_count += 1
            print(f"📷 Processing: {file_path.relative_to(current_dir)}")

            
            try:
                has_face = has_human_face(file_path)
            except Exception as e:
                print(f"  ⚠️ Error processing: {e}")
                continue

            if not has_face:
                no_face_count += 1

                
                relative_path = file_path.relative_to(current_dir)
                destination = no_face_dir / relative_path

                
                destination.parent.mkdir(parents=True, exist_ok=True)

                
                try:
                    shutil.move(str(file_path), str(destination))
                    print(f"  🚫 Moved to no_face/{relative_path}")
                    moved_count += 1
                except Exception as e:
                    print(f"  ❌ Failed to move: {e}")
            else:
                print(f"  ✅ Has face - keeping in place")

    
    print("\n" + "=" * 50)
    print("📊 SUMMARY")
    print("=" * 50)
    print(f"Total images processed: {image_count}")
    print(f"Images without faces: {no_face_count}")
    print(f"Images moved to 'no_face': {moved_count}")
    print(f"Images with faces (kept): {image_count - no_face_count}")

    if moved_count > 0:
        print(f"\n📁 Moved images to: {no_face_dir}")
    print("=" * 50)


if __name__ == "__main__":
    print("🔍 Face Detection Image Organizer")
    print("=" * 50)
    print("Processing images in:", Path.cwd())
    print("Images with faces will stay in place")
    print("Images WITHOUT faces will be moved to 'no_face/'")
    print("=" * 50 + "\n")

    response = input("Continue? (y/n): ").lower().strip()
    if response == "y":
        folderize_images()
    else:
        print("Operation cancelled.")
