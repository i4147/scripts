import sys
from pathlib import Path

from dh import fsz


def main() -> None:
    ext = sys.argv[1]
    total_size = 0
    count = 0
    cwd = Path.cwd()
    for f in cwd.rglob(f"*.{ext}"):
        total_size += f.stat().st_size
        count += 1
    print(f"Total number of .{ext} files: {count}")
    print(f"Total size of .{ext} files: {fsz(total_size)}")


if __name__ == "__main__":
    main()
