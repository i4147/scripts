from PIL.Image import Image
import pathlib
from sys import argv

from cv2 import VideoCapture, imwrite
from PIL import Image
from pytesseract import image_to_string
from termcolor import cprint


def process_image(imag) -> Image:
    img = Image.open(imag)
    return img.convert("L")


def extract_text(ff: str) -> bytes | dict[str, bytes | str] | str:
    return image_to_string(
        Image.open(ff).convert("L"),
        lang="eng",
        config="--oem 1 --psm 6",
    )


def main():
    cap = VideoCapture(argv[1])
    txtfile = f"{str(argv[1]).strip().replace('.mkv', '')}.txt"
    i = 1
    while True:
        im = cap.read()
        if i % 10 != 0:
            i += 1
            continue
        imwrite(f"{i!s}.jpg", im[1])
        text = extract_text(f"{i!s}.jpg")
        if text and len(text) > 10:
            cprint(f"frame {i} -->{text}", "cyan")
            with pathlib.Path(txtfile).open("a", encoding="utf-8") as fo:
                fo.write(text)
        else:
            cprint(f"frame {i} --> no text", "blue")
        pathlib.Path(f"{i!s}.jpg").unlink()
        i += 1


if __name__ == "__main__":
    main()
