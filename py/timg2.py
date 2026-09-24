from __future__ import annotations
import argparse
import math
import os
import sys
import numpy as np
from PIL import Image


class Timg:
    def __init__(self, width=80, height=24, method="auto"):
        self.width = width
        self.height = height
        self.method = method
        self.terminal = self.detect_terminal()

    def detect_terminal(self):
        term = os.environ.get("TERM", "")
        if "kitty" in term:
            return "kitty"
        elif os.environ.get("ITERM_PROFILE"):
            return "iterm2"
        elif "sixel" in term or os.environ.get("SIXEL"):
            return "sixel"
        else:
            return "ascii"

    def resize_image(self, img):
        target_height = self.height
        target_width = int(self.width * 2)
        img.thumbnail((target_width, target_height), Image.Resampling.LANCZOS)
        return img

    def image_to_ascii(self, img):
        chars = "@%#*+=-:. "
        img = img.convert("L")
        img = self.resize_image(img)
        ascii_art = []
        for y in range(img.height):
            line = ""
            for x in range(img.width):
                pixel = img.getpixel((x, y))
                char_index = int(pixel / 255 * (len(chars) - 1))
                line += chars[char_index]
            ascii_art.append(line)
        return "\n".join(ascii_art)

    def image_to_kitty(self, img):
        import base64
        from io import BytesIO

        buffer = BytesIO()
        img.save(buffer, format="PNG")
        img_data = base64.b64encode(buffer.getvalue()).decode()
        return f"\x1b_Gf=100,a=T,t=f;{img_data}\x1b\\\x1b_Ga=T,d=A\x1b\\"

    def image_to_iterm2(self, img):
        import base64
        from io import BytesIO

        buffer = BytesIO()
        img.save(buffer, format="PNG")
        img_data = base64.b64encode(buffer.getvalue()).decode()
        return f"\x1b]1337;File=inline=1;width={self.width}px;height={self.height}px:{img_data}\x07"

    def image_to_sixel(self, img):
        img = img.resize((self.width, self.height), Image.Resampling.LANCZOS)
        img = img.convert("RGB")
        sixel = '\x1bP0;1;0q"1;1;'
        for y in range(0, img.height, 6):
            for x in range(img.width):
                sixel_byte = 0
                for bit in range(6):
                    if y + bit < img.height:
                        r, g, b = img.getpixel((x, y + bit))
                        if (r + g + b) / 3 < 128:
                            sixel_byte |= 1 << bit
                if sixel_byte:
                    sixel += chr(63 + sixel_byte)
                else:
                    sixel += "?"
            sixel += "$"
        sixel += "\x1b\\"
        return sixel

    def display(self, image_path):
        try:
            img = Image.open(image_path)
            if getattr(img, "is_animated", False):
                img.seek(0)
            method = self.method
            if method == "auto":
                method = self.terminal
            if method == "kitty" and self.terminal == "kitty":
                output = self.image_to_kitty(img)
                print(output, end="")
            elif method == "iterm2" and "ITERM_PROFILE" in os.environ:
                output = self.image_to_iterm2(img)
                print(output, end="")
            elif method == "sixel":
                output = self.image_to_sixel(img)
                print(output, end="")
            else:
                ascii_art = self.image_to_ascii(img)
                print(ascii_art)
            return True
        except Exception as e:
            print(f"Error displaying image: {e}", file=sys.stderr)
            return False

    def display_multiple(self, image_paths):
        for i, path in enumerate(image_paths):
            if i > 0:
                print("\n" + "-" * 80)
            self.display(path)


def main():
    parser = argparse.ArgumentParser(
        description="Display images in the terminal", epilog="Supported formats: PNG, JPEG, GIF, BMP, etc."
    )
    parser.add_argument("images", nargs="+", help="Image files to display")
    parser.add_argument("-w", "--width", type=int, default=80, help="Display width in characters (default: 80)")
    parser.add_argument("-H", "--height", type=int, default=24, help="Display height in characters (default: 24)")
    parser.add_argument(
        "-m",
        "--method",
        choices=["auto", "ascii", "kitty", "iterm2", "sixel"],
        default="auto",
        help="Display method (default: auto)",
    )
    parser.add_argument("-l", "--list-methods", action="store_true", help="List available display methods")
    args = parser.parse_args()
    if args.list_methods:
        print("Available display methods:")
        print("  auto    - Automatically detect best method")
        print("  ascii   - ASCII art (works everywhere)")
        print("  kitty   - Kitty graphics protocol")
        print("  iterm2  - iTerm2 inline images")
        print("  sixel   - Sixel graphics")
        return 0
    timg = Timg(width=args.width, height=args.height, method=args.method)
    success = timg.display_multiple(args.images)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
