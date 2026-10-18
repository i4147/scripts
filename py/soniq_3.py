import os
import sys


def sort_uniq(filename: str) -> int:
    file_size = os.path.getsize(filename)
    if file_size > 1024 * 1024:
        import mmap

        with open(filename, "r+") as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                lines = mm.read().decode("utf-8").splitlines()
    else:
        with open(filename, "r") as f:
            lines = f.read().splitlines()
    unique_lines = sorted(set(lines))
    original_count = len(lines)
    new_count = len(unique_lines)
    lines_removed = original_count - new_count
    with open(filename, "w") as f:
        for line in unique_lines:
            f.write(line + "\n")
    return lines_removed


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python sort_uniq.py <filename>")
        sys.exit(1)
    filename = sys.argv[1]
    lines_removed = sort_uniq(filename)
    if lines_removed > 0:
        print(f"Removed {lines_removed} duplicate lines.")
    else:
        print("No change.")
