import sys
from collections import deque
from multiprocessing import get_context
from os import scandir as os_scandir
from pathlib import Path

from PIL import Image
from pytesseract import image_to_string


def get_files(path: str | Path, ext: list[str] | None = None) -> list[Path]:
    path = Path(path)
    skip_dirs = {".git", "__pycache__"}
    queue = deque([path])
    files = []
    while queue:
        current = queue.popleft()
        try:
            entries = current.iterdir()
        except (PermissionError, OSError):
            continue
        for item in entries:
            if item.is_symlink():
                continue
            if item.is_dir() and item.name not in skip_dirs:
                queue.append(item)
            elif item.is_file():
                if ext is None or item.suffix in ext:
                    files.append(item)
    return files


def extract_text(image_path: Path) -> bytes | dict[str, bytes | str] | str:
    img = Image.open(image_path)
    result = image_to_string(img, lang="eng", config="--oem 1 --psm 6")
    print("*" * 35)
    print(result)
    return result


def process_file(path: Path) -> None:
    path = Path(path)
    txtfile = path.with_suffix(".txt")
    if txtfile.exists():
        return
    print(f"Processing {path.name}")
    text = extract_text(path)
    if text and len(text) > 1:
        txtfile.write_text(text, encoding="utf-8")
        print(f"{txtfile} created.")
    else:
        print("No text found.")


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = [Path(p) for p in args] if args else get_files(cwd, ext=[".jpg", ".png"])
    if len(files) == 1:
        process_file(files[0])
        sys.exit(0)
    p = get_context("spawn").Pool(8)
    for _ in p.imap_unordered(process_file, files):
        pass
    p.close()
    p.join()


if __name__ == "__main__":
    main()
