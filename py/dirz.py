"""List directories in the current working directory, optionally with sizes.

By default only the directory names are printed, followed by a total count.
With ``-s`` / ``--size`` a third column shows the recursive size of each
directory (sum of all regular files underneath it, symlinks excluded), and
the total line gains the combined size.
"""

from __future__ import annotations

import argparse
from pathlib import Path


# --------------------------------------------------------------------------- #
# Directory size helper
# --------------------------------------------------------------------------- #
def dir_size(directory: Path) -> int:
    """Return the total size in bytes of all regular files under *directory*.

    Uses ``rglob('*')`` to walk the tree recursively.  Symlinks are skipped
    to avoid cycles and double-counting; unreadable files are ignored.
    """
    total = 0
    for entry in directory.rglob("*"):
        if entry.is_symlink():
            continue
        if entry.is_file():
            try:
                total += entry.stat().st_size
            except OSError:
                # Unreadable file: keep going rather than abort the whole run.
                pass
    return total


def human_size(num_bytes: int) -> str:
    """Return a compact human-readable representation of *num_bytes*.

    Examples: ``512B``, ``1.5KB``, ``3.2MB``.
    """
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        # Stop at the first unit that fits, or force PB for huge values.
        if size < 1024 or unit == "PB":
            if unit == "B":
                # No decimal point for raw bytes.
                return f"{int(size)}B"
            return f"{size:.1f}{unit}"
        size /= 1024


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args(argv=None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="List directories in the current directory.")
    parser.add_argument(
        "-s",
        "--size",
        action="store_true",
        help="also show the total size of each directory",
    )
    return parser.parse_args(argv)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main(argv=None) -> None:
    args = parse_args(argv)
    cwd = Path.cwd()

    # Only top-level directories in the CWD are considered.
    dirs = [p for p in cwd.glob("*") if p.is_dir()]

    # ----------------------------------------------------------------------- #
    # Optional size pass (only when --size was requested)
    # ----------------------------------------------------------------------- #
    sizes: dict[str, int] = {}
    formatted_sizes: dict[str, str] = {}
    max_size_len = 0

    if args.size:
        for d in dirs:
            sizes[d.name] = dir_size(d)
        formatted_sizes = {name: human_size(b) for name, b in sizes.items()}
        if formatted_sizes:
            max_size_len = max(len(s) for s in formatted_sizes.values())

    # ----------------------------------------------------------------------- #
    # Output
    # ----------------------------------------------------------------------- #
    for d in dirs:
        line = f"  -  {d.name}"
        if args.size:
            line += f"  {formatted_sizes[d.name]:>{max_size_len}}"
        print(line)

    # Total line: always shows the directory count; size appended with -s.
    total_line = f"total: {len(dirs)} dirs"
    if args.size:
        total_line += f"  {human_size(sum(sizes.values()))}"
    print(total_line)


if __name__ == "__main__":
    main()
