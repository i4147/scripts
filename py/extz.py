"""Count files by extension in the current directory tree.

By default two columns are printed: the extension and the number of files.
With ``-s`` / ``--size`` a third column shows the total size of the files
belonging to each extension.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path


# --------------------------------------------------------------------------- #
# Filesystem traversal
# --------------------------------------------------------------------------- #
def walk_files(directory: Path):
    """Recursively yield regular files under *directory*.

    Symlinks and anything named ``.git`` are skipped.  Symlinks are excluded
    to avoid cycles and double-counting; ``.git`` is excluded because its
    contents are usually noise for this kind of report.
    """
    for entry in directory.iterdir():
        # Skip symlinks entirely (files or directories).
        if entry.is_symlink():
            continue
        # Skip the .git directory (and any file literally named ".git").
        if entry.name == ".git":
            continue
        if entry.is_file():
            yield entry
        elif entry.is_dir():
            # Recurse into subdirectories.
            yield from walk_files(entry)


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #
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
    parser = argparse.ArgumentParser(description="Count files by extension in the current directory tree.")
    parser.add_argument(
        "-s",
        "--size",
        action="store_true",
        help="also show the total size of files for each extension",
    )
    return parser.parse_args(argv)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main(argv=None) -> None:
    args = parse_args(argv)
    current_dir = Path.cwd()

    # Number of files per extension, and (optionally) total bytes per extension.
    extension_counter: Counter[str] = Counter()
    extension_sizes: Counter[str] = Counter()

    for path in walk_files(current_dir):
        # Files without a suffix (e.g. "Makefile") go into a ".no_ext" bucket.
        ext = path.suffix if path.suffix else ".no_ext"
        extension_counter[ext] += 1

        if args.size:
            try:
                extension_sizes[ext] += path.stat().st_size
            except OSError:
                # Unreadable / broken file: keep the count, ignore the size.
                pass

    if not extension_counter:
        print("No files found.")
        return

    # ----------------------------------------------------------------------- #
    # Column widths for aligned output
    # ----------------------------------------------------------------------- #
    max_ext_len = max(len(ext) for ext in extension_counter)
    max_count_len = max(len(str(count)) for count in extension_counter.values())

    # Pre-format sizes (only needed when --size was passed) and compute the
    # width of the third column from the formatted strings.
    formatted_sizes: dict[str, str] = {}
    max_size_len = 0
    if args.size:
        formatted_sizes = {ext: human_size(extension_sizes.get(ext, 0)) for ext in extension_counter}
        max_size_len = max(len(s) for s in formatted_sizes.values())

    # ----------------------------------------------------------------------- #
    # Output
    # ----------------------------------------------------------------------- #
    print("extensions found:")
    for ext, count in sorted(extension_counter.items()):
        line = f" {ext:<{max_ext_len}}  {count:>{max_count_len}}"
        if args.size:
            line += f"  {formatted_sizes[ext]:>{max_size_len}}"
        print(line)


if __name__ == "__main__":
    main()
