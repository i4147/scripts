from PIL.ImageFile import ImageFile
import argparse
import sys
import os
from PIL import Image


def resize_image(img: ImageFile, terminal_width: int, terminal_height: int, max_width=None, max_height=None):
    orig_width, orig_height = img.size

    if max_width and max_height:
        target_width = min(max_width, terminal_width)
        target_height = min(max_height, terminal_height)
    else:
        target_width = terminal_width
        target_height = terminal_height

    aspect = orig_height / orig_width
    new_width = target_width
    new_height = int(target_width * aspect)

    if new_height > target_height:
        new_height = target_height
        new_width = int(target_height / aspect)

    return img.resize((new_width, new_height), Image.Resampling.LANCZOS)


def rgb_to_ansi(r, g, b) -> str:
    return f"\033[38;2;{r};{g};{b}m"


def image_to_ansi(img) -> str:
    img = img.convert("RGB")
    width, height = img.size

    output_lines = []

    for y in range(height):
        line = []
        for x in range(width):
            r, g, b = img.getpixel((x, y))
            line.append(f"{rgb_to_ansi(r, g, b)}██")
        output_lines.append("".join(line))

    output = "\n".join(output_lines) + "\033[0m"
    return output


def image_to_ansi_blocks(img) -> str:
    img = img.convert("RGB")
    width, height = img.size

    if height % 2 != 0:
        img = img.crop((0, 0, width, height - 1))
        height -= 1

    output_lines = []

    for y in range(0, height, 2):
        line = []
        for x in range(width):
            r1, g1, b1 = img.getpixel((x, y))
            r2, g2, b2 = img.getpixel((x, y + 1))

            line.append(f"\033[38;2;{r1};{g1};{b1}m\033[48;2;{r2};{g2};{b2}m▀")

        output_lines.append("".join(line))

    output = "\n".join(output_lines) + "\033[0m"
    return output


def get_terminal_size() -> tuple[int, int]:
    try:
        columns, rows = os.get_terminal_size()
        return columns, rows
    except:
        return 80, 24


def catimg(image_path, width=None, height=None, use_half_blocks=True) -> None:
    try:
        img = Image.open(image_path)

        term_width, term_height = get_terminal_size()

        if use_half_blocks:
            term_height *= 2

        img = resize_image(img, term_width, term_height, width, height)

        if use_half_blocks:
            output = image_to_ansi_blocks(img)
        else:
            output = image_to_ansi(img)

        print(output)

    except FileNotFoundError:
        print(f"Error: File '{image_path}' not found", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Display images in terminal with true color support", epilog="Example: catimg image.jpg"
    )

    parser.add_argument("image", help="Path to image file")
    parser.add_argument("-w", "--width", type=int, help="Maximum width in characters")
    parser.add_argument("-H", "--height", type=int, help="Maximum height in characters")
    parser.add_argument(
        "--no-half-blocks", action="store_true", help="Disable half-block characters (lower vertical resolution)"
    )

    args = parser.parse_args()

    catimg(args.image, args.width, args.height, use_half_blocks=not args.no_half_blocks)


if __name__ == "__main__":
    main()
