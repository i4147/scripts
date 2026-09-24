import sys
import argparse
import mmap
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import List, Tuple, Optional
import os
from dh import TXT_EXT, BIN_EXT

MMAP_THRESHOLD = 1024 * 1024


def is_text_file(file_path: Path) -> bool:
    return (file_path.suffix.lower() in TXT_EXT) and (not file_path.suffix.lower() in BIN_EXT)


def process_small_file(file_path: Path, preserve_single: bool) -> tuple[str, int, int]:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        original_count = len(lines)

        if preserve_single:
            new_lines = preserve_single_blank_lines(lines)
        else:
            new_lines = [line for line in lines if line.strip() != ""]

        blank_lines_removed = original_count - len(new_lines)

        if blank_lines_removed > 0:
            content = "".join(new_lines)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

        return (str(file_path), original_count, blank_lines_removed)

    except Exception as e:
        return (str(file_path), 0, f"Error: {str(e)}")


def process_large_file_mmap(file_path: Path, preserve_single: bool) -> tuple[str, int, int]:
    try:
        with open(file_path, "r+b") as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                content = mm.read().decode("utf-8", errors="ignore")

            lines = content.splitlines(keepends=True)
            original_count = len(lines)

            if preserve_single:
                new_lines = preserve_single_blank_lines(lines)
            else:
                new_lines = [line for line in lines if line.strip() != ""]

            blank_lines_removed = original_count - len(new_lines)

            if blank_lines_removed > 0:
                new_content = "".join(new_lines)
                f.seek(0)
                f.write(new_content.encode("utf-8"))
                f.truncate()

        return (str(file_path), original_count, blank_lines_removed)

    except Exception as e:
        return (str(file_path), 0, f"Error: {str(e)}")


def preserve_single_blank_lines(lines: list[str]) -> list[str]:
    new_lines = []
    prev_blank = False

    for line in lines:
        is_blank = line.strip() == ""

        if is_blank:
            if not prev_blank:
                new_lines.append(line)
            prev_blank = True
        else:
            new_lines.append(line)
            prev_blank = False

    while len(new_lines) > 1 and new_lines[-1].strip() == "":
        new_lines.pop()

    return new_lines


def remove_blank_lines(file_path: Path, preserve_single: bool = False) -> tuple[str, int, int]:
    try:
        file_size = file_path.stat().st_size

        if file_size > MMAP_THRESHOLD:
            return process_large_file_mmap(file_path, preserve_single)
        else:
            return process_small_file(file_path, preserve_single)

    except Exception as e:
        return (str(file_path), 0, f"Error: {str(e)}")


def find_text_files(directories: list[Path]) -> list[Path]:
    text_files = []

    for directory in directories:
        if not directory.exists():
            print(f"Warning: Directory '{directory}' does not exist, skipping...")
            continue
        if not directory.is_dir():
            print(f"Warning: '{directory}' is not a directory, skipping...")
            continue

        for file_path in directory.rglob("*"):
            if file_path.is_file() and is_text_file(file_path):
                text_files.append(file_path)

    return text_files


def process_files_parallel(
    files: list[Path], preserve_single: bool, max_workers: int = None
) -> list[tuple[str, int, int]]:
    results = []

    if max_workers is None:
        max_workers = os.cpu_count()

    large_files = []
    small_files = []

    for file_path in files:
        try:
            if file_path.stat().st_size > MMAP_THRESHOLD:
                large_files.append(file_path)
            else:
                small_files.append(file_path)
        except OSError:
            small_files.append(file_path)

    print(f"  Small files (<1MB): {len(small_files):,}")
    print(f"  Large files (≥1MB): {len(large_files):,} (using mmap)")

    all_files = large_files + small_files

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {
            executor.submit(remove_blank_lines, file_path, preserve_single): file_path for file_path in all_files
        }

        for future in as_completed(future_to_file):
            file_path = future_to_file[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                results.append((str(file_path), 0, f"Error: {str(e)}"))

    return results


def format_size(size_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def print_results(results: list[tuple[str, int, int]], base_dir: Path, preserve_single: bool):
    print("\n" + "=" * 42)
    if preserve_single:
        print("BLANK LINE CLEANUP REPORT (Preserving single blank lines)")
    else:
        print("BLANK LINE CLEANUP REPORT (Removing all blank lines)")
    print("=" * 42)

    results.sort(key=lambda x: x[0])

    total_original_lines = 0
    total_blank_removed = 0
    files_modified = 0
    files_with_errors = 0
    large_files_processed = 0

    for rel_path, original_lines, blank_removed in results:
        try:
            path = Path(rel_path)
            display_path = path.relative_to(base_dir) if base_dir in path.parents or base_dir == path else path
        except (ValueError, OSError):
            display_path = rel_path

        if isinstance(blank_removed, str):
            print(f"\n❌ {display_path}")
            print(f"   {blank_removed}")
            files_with_errors += 1
        elif blank_removed > 0:
            try:
                file_size = path.stat().st_size
                size_str = format_size(file_size)
                is_large = file_size > MMAP_THRESHOLD
            except OSError:
                size_str = "unknown"
                is_large = False

            method = " [mmap]" if is_large else ""
            if is_large:
                large_files_processed += 1

            print(f"\n✅ {display_path} ({size_str}){method}")
            print(f"   Lines: {original_lines:,} → {original_lines - blank_removed:,} (-{blank_removed:,})")
            total_original_lines += original_lines
            total_blank_removed += blank_removed
            files_modified += 1
        else:
            try:
                file_size = path.stat().st_size
                size_str = format_size(file_size)
            except OSError:
                size_str = "unknown"

            print(f"\n⏭️  {display_path} ({size_str})")
            print(f"   No blank lines found (total lines: {original_lines:,})")

    print("\n" + "=" * 42)
    print("SUMMARY")
    print("=" * 42)
    print(f"Files processed:      {len(results):,}")
    print(f"Files modified:       {files_modified:,}")
    print(f"  Large files (mmap): {large_files_processed:,}")
    print(f"Files with errors:    {files_with_errors:,}")
    print(f"Total lines removed:  {total_blank_removed:,}")
    if files_modified > 0:
        avg_removed = total_blank_removed / files_modified
        print(f"Average per file:     {avg_removed:.1f}")
    print("=" * 42)


def main():
    parser = argparse.ArgumentParser(
        description="Remove blank lines from text files recursively (with mmap for large files)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Remove all blank lines in current directory:
    %(prog)s
  
  Remove blank lines in specific directories:
    %(prog)s /path/to/dir1 /path/to/dir2
  
  Preserve single blank lines:
    %(prog)s -1
  
  Process multiple directories preserving single blank lines:
    %(prog)s src/ tests/ -1
        """,
    )

    parser.add_argument("directories", nargs="*", type=Path, help="Directories to process (default: current directory)")

    parser.add_argument(
        "-1",
        dest="preserve_single",
        action="store_true",
        help="Preserve single blank lines (remove only multiple consecutive blank lines)",
    )

    parser.add_argument(
        "-w", "--workers", type=int, default=None, help="Number of worker processes (default: number of CPU cores)"
    )

    parser.add_argument(
        "-t",
        "--threshold",
        type=int,
        default=MMAP_THRESHOLD,
        help=f"File size threshold for using mmap in bytes (default: {MMAP_THRESHOLD:,} = 1MB)",
    )

    args = parser.parse_args()

    global MMAP_THRESHOLD
    MMAP_THRESHOLD = args.threshold

    if args.directories:
        directories = [d.resolve() for d in args.directories]
    else:
        directories = [Path.cwd()]

    base_dir = Path.cwd()

    print(f"Searching for text files in:")
    for d in directories:
        print(f"  • {d}")

    print(f"\nmmap threshold: {format_size(MMAP_THRESHOLD)}")

    text_files = find_text_files(directories)

    if not text_files:
        print("\nNo text files found in specified directories.")
        return

    print(f"\nFound {len(text_files):,} text file(s) to process")

    if args.preserve_single:
        print("Mode: Preserving single blank lines")
    else:
        print("Mode: Removing all blank lines")

    print(f"\nProcessing with {args.workers or os.cpu_count()} workers...")
    results = process_files_parallel(text_files, args.preserve_single, args.workers)

    print_results(results, base_dir, args.preserve_single)


if __name__ == "__main__":
    main()
