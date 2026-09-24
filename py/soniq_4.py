from __future__ import annotations

import mmap
import sys
from multiprocessing import Pool, cpu_count
from pathlib import Path

from dh import is_binary

THRESHOLD = 1024 * 1024


def _process_chunk(chunk: list[str]) -> list[str]:
    return [line.strip() for line in chunk if line.strip()]


def read_lines(path: Path) -> list[str]:
    sz = path.stat().st_size
    try:
        if sz > THRESHOLD:
            with open(path, encoding="utf-8", errors="ignore") as f:
                with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                    data = mm.read().decode("utf-8", "ignore")
                    return data.splitlines()
        else:
            return path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except (UnicodeDecodeError, ValueError) as e:
        print(f"Warning: Could not read file as text: {e}")
        return []


def sort_uniq(path: Path) -> tuple[int, list[str]]:
    lines = read_lines(path)
    original_count = len(lines)
    if not original_count:
        return (0, [])
    if original_count > 1000:
        chunk_size = max(1, len(lines) // cpu_count())
        chunks = [lines[i : i + chunk_size] for i in range(0, len(lines), chunk_size)]
        with Pool(processes=min(cpu_count(), len(chunks))) as pool:
            processed_chunks = pool.map(_process_chunk, chunks)
        all_lines = [line for chunk in processed_chunks for line in chunk]
    else:
        all_lines = [line.strip() for line in lines if line.strip()]
    seen = set()
    duplicates = set()
    for line in all_lines:
        if line in seen:
            duplicates.add(line)
        else:
            seen.add(line)
    unique_sorted = sorted(seen)
    lines_removed = len(all_lines) - len(unique_sorted)
    if lines_removed > 0 or original_count != len(unique_sorted):
        path.write_text("\n".join(unique_sorted), encoding="utf-8")
    return (lines_removed, list(duplicates))


if __name__ == "__main__":
    args = sys.argv[1:]
    quiet = "--quiet" in args or "-q" in args
    filename_arg = next((a for a in args if not a.startswith("--")), None)
    if not filename_arg:
        print("Usage: python sort_uniq_mp.py <filename> [--quiet|-q]")
        print("  --quiet, -q : Only show count, not the actual duplicate lines")
        sys.exit(1)
    path = Path(filename_arg)
    if not path.exists():
        print(f"Error: File not found: {path}")
        sys.exit(1)
    if path.is_dir():
        print(f"Error: {path} is a directory, not a file")
        sys.exit(1)
    if is_binary(path):
        print(f"Skipping binary file: {path.name}")
        sys.exit(0)
    try:
        removed, duplicates = sort_uniq(path)
        if removed > 0:
            print(f"\n✓ {removed} duplicate{('s' if removed != 1 else '')} removed and file sorted")
            if not quiet and duplicates:
                print("\nDuplicate lines removed:")
                sorted_dupes = sorted(duplicates)
                for line in sorted_dupes[:50]:
                    print(f"  {line}")
                if len(sorted_dupes) > 50:
                    print(f"... ({len(sorted_dupes) - 50} more duplicate lines not shown)")
            elif quiet:
                print("  (Use without --quiet to see the actual duplicate lines)")
        else:
            print("✓ File sorted (all lines were unique)")
    except Exception as e:
        print(f"Error processing file: {e}")
        sys.exit(1)
