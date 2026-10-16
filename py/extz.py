from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path


def walk_files(directory: Path):
    for entry in directory.iterdir():
        if entry.is_symlink():
            continue

        if entry.name == ".git":
            continue
        if entry.is_file():
            yield entry
        elif entry.is_dir():
            yield from walk_files(entry)


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if size < 1024 or unit == "PB":
            if unit == "B":
                return f"{int(size)}B"
            return f"{size:.1f}{unit}"
        size /= 1024


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Count files by extension in the current directory tree.")
    parser.add_argument(
        "-s",
        "--size",
        action="store_true",
        help="also show the total size of files for each extension",
    )
    return parser.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    current_dir = Path.cwd()

    extension_counter: Counter[str] = Counter()
    extension_sizes: Counter[str] = Counter()

    for path in walk_files(current_dir):
        ext = path.suffix if path.suffix else ".no_ext"
        extension_counter[ext] += 1

        if args.size:
            try:
                extension_sizes[ext] += path.stat().st_size
            except OSError:
                pass

    if not extension_counter:
        print("No files found.")
        return

    max_ext_len = max(len(ext) for ext in extension_counter)
    max_count_len = max(len(str(count)) for count in extension_counter.values())

    formatted_sizes: dict[str, str] = {}
    max_size_len = 0
    if args.size:
        formatted_sizes = {ext: human_size(extension_sizes.get(ext, 0)) for ext in extension_counter}
        max_size_len = max(len(s) for s in formatted_sizes.values())

    print("extensions found:")
    for ext, count in sorted(extension_counter.items()):
        line = f" {ext:<{max_ext_len}}  {count:>{max_count_len}}"
        if args.size:
            line += f"  {formatted_sizes[ext]:>{max_size_len}}"
        print(line)


if __name__ == "__main__":
    main()
