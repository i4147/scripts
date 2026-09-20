import sys
from pathlib import Path
from dh import get_files
from pbar import Pbar
from pytesseract import image_to_pdf_hocr


def process_file(fp) -> None:
    result = image_to_pdf_hocr(fp)
    print(result)
    return result


def main() -> None:
    cwd = Path("/sdcard/DCIM/jpg")
    args = sys.argv[1:]
    if args:
        for arg in args:
            p = Path(arg)
            if p.is_file():
                files.append(p)
            if p.is_dir():
                files.extend(get_files(p))
    else:
        files = get_files(cwd, e=[".jpg"])
    with Pbar("") as pbar:
        for f in pbar.wrap(files):
            process_file(f)


if __name__ == "__main__":
    sys.exit(main())
