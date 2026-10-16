import mmap
import re
import sys
from pathlib import Path

JSON_PATH = Path("/sdcard/data/pip.json")

DICT_PATTERN = re.compile(rb'"([^"\\]+)"\s*:\s*(\d+)')

PAIR_PATTERN = re.compile(rb'"([^"\\]+)"\s*,\s*(\d+)')


def pick_pattern(mm):
    i, n = 0, len(mm)
    while i < n and mm[i] in b" \t\r\n":
        i += 1
    return DICT_PATTERN if mm[i : i + 1] == b"{" else PAIR_PATTERN


def main():
    if len(sys.argv) > 1:
        keyword = sys.argv[1]
    else:
        keyword = input("Search package: ").strip()
        if not keyword:
            print("No keyword given.")
            return

    kw = keyword.lower().encode()
    matches = []

    with JSON_PATH.open("rb") as f:
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            pattern = pick_pattern(mm)
            for m in pattern.finditer(mm):
                name = m.group(1)
                if kw in name.lower():
                    matches.append((name.decode("utf-8"), int(m.group(2))))

    if not matches:
        print(f"No matches for '{keyword}'.")
        return

    matches.sort(key=lambda x: x[1], reverse=True)
    for name, dl in matches:
        print(f"{name}  {dl}")


if __name__ == "__main__":
    main()
