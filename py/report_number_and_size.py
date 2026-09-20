import sys
from pathlib import Path


def main() -> None:
    ext = sys.argv[1]
    total_size = 0
    count = 0
    dir = Path.cwd()
    for f in dir.rglob(f"*.{ext}"):
        total_size += f.stat().st_size
        count += 1
    print(f"Total number of .{ext} files: {count}")
    print(f"Total size of .{ext} files: {total_size} bytes")


if __name__ == "__main__":
    main()
