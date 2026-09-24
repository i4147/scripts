from pathlib import Path
import cv2
import numpy as np
import pytesseract

SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".tiff", ".bmp", ".webp"}
BASE_DIR = Path.cwd()
OUTPUT_DIR = BASE_DIR / "ocr_ready"


def deskew(image):
    coords = np.column_stack(np.where(image > 0))
    if coords.size == 0:
        return image
    angle = cv2.minAreaRect(coords)[-1]
    angle = -(90 + angle) if angle < -45 else -angle
    h, w = image.shape[:2]
    center = w // 2, h // 2
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def preprocess_image(img_path: Path):
    img = cv2.imread(str(img_path))
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    gray = cv2.fastNlMeansDenoising(gray, None, 30, 7, 21)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 2)
    kernel = np.ones((1, 1), np.uint8)
    cleaned = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
    return deskew(cleaned)


def should_skip(path: Path) -> bool:
    if OUTPUT_DIR in path.parents:
        return True
    return path.suffix.lower() not in SUPPORTED_EXT


def process() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    for path in BASE_DIR.rglob("*"):
        if should_skip(path):
            continue
        relative = path.relative_to(BASE_DIR)
        out_img_path = OUTPUT_DIR / relative
        out_txt_path = out_img_path.with_suffix(".txt")
        out_img_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Processing: {relative}")
        processed = preprocess_image(path)
        if processed is None:
            continue
        cv2.imwrite(str(out_img_path), processed)
        text = pytesseract.image_to_string(processed, config="--oem 1 --psm 6")
        Path(out_txt_path).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    process()
    print("Done. Images + OCR text saved in ./ocr_ready")
