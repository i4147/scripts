import pathlib
import re
import sys

HEX_RE = re.compile("^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def hex_value(color: str) -> int:
    return int(color.lstrip("#"), 16)


def main(path: str) -> None:
    with pathlib.Path(path).open(encoding="utf-8") as f:
        colors = [line.strip() for line in f if HEX_RE.match(line.strip())]
    colors.sort(key=hex_value)
    with pathlib.Path(path).open("w", encoding="utf-8") as f:
        f.writelines((c.lower() + "\n" for c in colors))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: sort_colors.py colors.txt")
        sys.exit(1)
    main(sys.argv[1])
