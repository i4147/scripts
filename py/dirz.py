from __future__ import annotations
import argparse
from pathlib import Path


def dir_size(directory: Path) -> int:
    total = 0
    for entry in directory.rglob("*"):
        if entry.is_symlink():
            continue
        if entry.is_file():
            try:
                total += entry.stat().st_size
            except OSError:
                pass
    return total


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if size < 1024 or unit == "PB":
            if unit == "B":
                return f"{int(size)}B"
            return f"{size:.1f}{unit}"
        size /= 1024


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List directories in the current directory.")
    parser.add_argument(
        "-s",
        "--size",
        action="store_true",
        help="also show the total size of each directory",
    )
    return parser.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    cwd = Path.cwd()
    dirs = [p for p in cwd.glob("*") if p.is_dir()]
    sizes: dict[str, int] = {}
    formatted_sizes: dict[str, str] = {}
    max_size_len = 0
    if args.size:
        for d in dirs:
            sizes[d.name] = dir_size(d)
        formatted_sizes = {name: human_size(b) for name, b in sizes.items()}
        if formatted_sizes:
            max_size_len = max(len(s) for s in formatted_sizes.values())
    for d in dirs:
        line = f"  -  {d.name}"
        if args.size:
            line += f"  {formatted_sizes[d.name]:>{max_size_len}}"
        print(line)
    total_line = f"total: {len(dirs)} dirs"
    if args.size:
        total_line += f"  {human_size(sum(sizes.values()))}"
    print(total_line)


if __name__ == "__main__":
    main()
