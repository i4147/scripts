import operator
import os
import sys
from collections import defaultdict
from pathlib import Path

SAVE_TO_FILE = False


def scan_directory(path: str = "."):
    total_size = 0
    file_count = 0
    folder_count = 0
    extensions = set()
    size_by_ext = defaultdict(int)
    for root, dirs, files in os.walk(path):
        folder_count += len(dirs)
        for filename in files:
            file_count += 1
            full_path = Path(root) / filename
            try:
                size = full_path.stat().st_size
            except OSError:
                size = 0
            total_size += size
            ext = full_path.suffix
            ext = ext.lower() if ext else "(no extension)"
            extensions.add(ext)
            size_by_ext[ext] += size
    return (
        total_size,
        file_count,
        folder_count,
        extensions,
        size_by_ext,
    )


def write_summary(filename: Path) -> None:
    (
        total_size,
        file_count,
        folder_count,
        extensions,
        size_by_ext,
    ) = scan_directory()
    with filename.open("w", encoding="utf-8") as f:
        f.write(f"total size: {total_size} bytes\n")
        f.write(f"extensions:\n{'\n   - '.join(sorted(extensions))}\n")
        f.write(f"number of files: {file_count}\n")
        f.write(f"number of folders: {folder_count}\n")
        f.write("size by extension:\n")
        for ext, size in sorted(size_by_ext.items(), key=operator.itemgetter(1), reverse=True):
            f.write(f"  {ext}: {size} bytes\n")
            print(f"  {ext}: {size} bytes\n")


if __name__ == "__main__":
    if SAVE_TO_FILE:
        outf = Path(".dirinfo")
    else:
        outf = sys.stderr
    write_summary(outf)
"""
i added SAVE_TO_FILE to make saving report
to file optional so that i can change it manually
but dudnt updated write_summary function
but its not a good idea(i may forget about it)
- add -s cli arg to optionally save to file
- without -s just print result
- default is no write to file
- add -i cli arg to save a matplotlib
bar chart (file_types and sizes) as an image
in current dir
- add -t cli arg to get type of matplotlib chart
"""
