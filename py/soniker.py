import mmap
import os
import sys


def sort_and_dedup(file_name: str, show_removed: bool = False) -> None:
    file_size = os.path.getsize(file_name)
    if file_size > 5 * 1024 * 1024:
        with open(file_name, "r+b") as f:
            with mmap.mmap(f.fileno(), 0) as mm:
                lines = mm.read().decode().splitlines()
    else:
        with open(file_name, "r") as f:
            lines = f.readlines()
    unique_lines = sorted(set(lines))
    removed_lines = [line for line in lines if lines.count(line) > 1]
    with open(file_name, "w") as f:
        f.writelines(unique_lines)
    print(f"Removed {len(removed_lines)} lines.")
    if show_removed:
        print("Removed lines:")
        for line in removed_lines:
            print(line.strip())


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python sort_uniq.py <file_name> [-d]")
        sys.exit(1)
    file_name = sys.argv[1]
    show_removed = "-d" in sys.argv
    sort_and_dedup(file_name, show_removed)
