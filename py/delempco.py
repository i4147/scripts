from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from dh import is_binary, should_skip


class ANSI:
    RESET = "\x1b[0m"
    BOLD = "\x1b[1m"
    DIM = "\x1b[2m"
    CYAN = "\x1b[36m"
    GREEN = "\x1b[32m"
    YELLOW = "\x1b[33m"
    RED = "\x1b[31m"

    @classmethod
    def disable(cls):
        for attr in dir(cls):
            if not attr.startswith("_") and attr != "disable":
                setattr(cls, attr, "")


@dataclass
class FileResult:
    path: Path
    status: str
    total_lines: int = 0
    removed_lines: int = 0
    error_message: str = ""
    is_bin: bool = False


@dataclass
class ProcessingStats:
    total_files: int = 0
    text_files: int = 0
    binary_files: int = 0
    files_modified: int = 0
    lines_removed: int = 0
    errors_count: int = 0
    results: list[FileResult] = field(default_factory=list)


def remove_blank_lines(file_path: Path, remove_spaces: bool = False) -> tuple[int, int]:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except OSError as e:
        raise OSError(f"Failed to read file: {e}")
    total_lines = len(lines)
    if remove_spaces:
        filtered = [line for line in lines if line.strip()]
    else:
        filtered = [line for line in lines if line not in ("\n", "\r\n", "\r")]
    removed_lines = total_lines - len(filtered)
    if removed_lines > 0:
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.writelines(filtered)
        except OSError as e:
            raise OSError(f"Failed to write file: {e}")
    return (total_lines, removed_lines)


def process_file_worker(base_dir: Path, file_path: Path, remove_spaces: bool = False) -> FileResult:
    result = FileResult(path=file_path, status="error")
    try:
        try:
            with open(file_path, "rb") as f:
                first_8kb = f.read(8192)
        except OSError:
            result.status = "error"
            result.error_message = "Permission denied"
            return result
        if is_binary(file_path, first_8kb):
            result.status = "skipped_binary"
            result.is_bin = True
            return result
        total_lines, removed_lines = remove_blank_lines(file_path, remove_spaces)
        result.total_lines = total_lines
        result.removed_lines = removed_lines
        if removed_lines > 0:
            result.status = "processed"
        else:
            result.status = "unchanged"
    except OSError as e:
        result.status = "error"
        result.error_message = str(e)
    except Exception as e:
        result.status = "error"
        result.error_message = f"Unexpected error: {e}"
    return result


def discover_files(directories: list[str]) -> tuple[list[Path], int]:
    files = []
    skipped_dirs = 0
    for dir_str in directories:
        dir_path = Path(dir_str).resolve()
        if not dir_path.exists():
            print(
                f"{ANSI.YELLOW}⚠ Directory not found: {dir_path}{ANSI.RESET}",
                file=sys.stderr,
            )
            skipped_dirs += 1
            continue
        if not dir_path.is_dir():
            print(
                f"{ANSI.YELLOW}⚠ Not a directory: {dir_path}{ANSI.RESET}",
                file=sys.stderr,
            )
            skipped_dirs += 1
            continue
        for file_path in dir_path.rglob("*"):
            if file_path.is_file() and (not should_skip(file_path)):
                files.append(file_path)
    return (files, skipped_dirs)


def print_header():
    print(f"\n{ANSI.CYAN}╔════════════════════════════════════════════╗{ANSI.RESET}")
    print(f"{ANSI.CYAN}║{ANSI.RESET}         Blank Line Remover              {ANSI.CYAN}║{ANSI.RESET}")
    print(f"{ANSI.CYAN}╚════════════════════════════════════════════╝{ANSI.RESET}\n")


def print_directory_list(directories: list[str]):
    print("Processing directories:")
    for dir_str in directories:
        print(f"  {ANSI.DIM}•{ANSI.RESET} {Path(dir_str).resolve()}")
    print()


def print_mode(remove_spaces: bool):
    if remove_spaces:
        print(f"Mode: {ANSI.BOLD}Remove blank lines and whitespace-only lines{ANSI.RESET}\n")
    else:
        print(f"Mode: {ANSI.BOLD}Remove blank lines only{ANSI.RESET}\n")


def print_progress(current: int, total: int):
    pct = current / total * 40 if total > 0 else 0
    print(f"\r  Progress: {current}/{total} ({pct:.0f}%)", end="", flush=True)


def print_separator():
    print(f"\n{ANSI.CYAN}{'─' * 40}{ANSI.RESET}\n")


def print_results(stats: ProcessingStats, base_dirs: list[Path]):
    processed = [r for r in stats.results if r.status == "processed"]
    unchanged = [r for r in stats.results if r.status == "unchanged"]
    skipped_binary = [r for r in stats.results if r.status == "skipped_binary"]
    errors = [r for r in stats.results if r.status == "error"]
    if processed:
        print(f"{ANSI.GREEN}✓ Modified files:{ANSI.RESET}\n")
        for result in sorted(processed, key=lambda r: r.path):
            try:
                rel_path = result.path.relative_to(Path.cwd())
            except ValueError:
                rel_path = result.path
            print(f"  {ANSI.GREEN}●{ANSI.RESET} {rel_path}")
            print(f"    {ANSI.DIM}Lines: {result.total_lines}  →  Removed: {result.removed_lines}{ANSI.RESET}")
    if unchanged:
        print(f"\n{ANSI.DIM}○ Unchanged files (no blank lines):{ANSI.RESET}\n")
        for result in sorted(unchanged, key=lambda r: r.path)[:5]:
            try:
                rel_path = result.path.relative_to(Path.cwd())
            except ValueError:
                rel_path = result.path
            print(f"  {ANSI.DIM}○ {rel_path}{ANSI.RESET}")
        if len(unchanged) > 5:
            print(f"  {ANSI.DIM}... and {len(unchanged) - 5} more{ANSI.RESET}")
    if skipped_binary:
        print(f"\n{ANSI.YELLOW}⊘ Skipped binary files: {len(skipped_binary)}{ANSI.RESET}")
        for result in sorted(skipped_binary, key=lambda r: r.path)[:5]:
            try:
                rel_path = result.path.relative_to(Path.cwd())
            except ValueError:
                rel_path = result.path
            print(f"  {ANSI.YELLOW}⊘ {rel_path}{ANSI.RESET}")
        if len(skipped_binary) > 5:
            print(f"  {ANSI.YELLOW}... and {len(skipped_binary) - 5} more binary files{ANSI.RESET}")
    if errors:
        print(f"\n{ANSI.RED}✗ Errors:{ANSI.RESET}\n")
        for result in sorted(errors, key=lambda r: r.path):
            try:
                rel_path = result.path.relative_to(Path.cwd())
            except ValueError:
                rel_path = result.path
            print(f"  {ANSI.RED}✗ {rel_path}{ANSI.RESET}")
            print(f"    {ANSI.DIM}{result.error_message}{ANSI.RESET}")


def print_summary(stats: ProcessingStats):
    print_separator()
    print(f"{ANSI.BOLD}Summary:{ANSI.RESET}")
    print(f"  Total files found:     {ANSI.BOLD}{stats.total_files:,}{ANSI.RESET}")
    print(f"  Text files processed:  {ANSI.BOLD}{stats.text_files:,}{ANSI.RESET}")
    print(f"  Binary files skipped:  {ANSI.BOLD}{stats.binary_files:,}{ANSI.RESET}")
    print(f"  Files modified:        {ANSI.BOLD}{ANSI.GREEN}{stats.files_modified:,}{ANSI.RESET}")
    print(f"  Lines removed:         {ANSI.BOLD}{ANSI.GREEN}{stats.lines_removed:,}{ANSI.RESET}")
    if stats.errors_count > 0:
        print(f"  Errors:                {ANSI.BOLD}{ANSI.RED}{stats.errors_count:,}{ANSI.RESET}")
    print_separator()


def main():
    parser = argparse.ArgumentParser(
        description="Recursively remove blank lines from text files with parallel processing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\nExamples:\n\n  python blank_remover.py\n\n\n  python blank_remover.py src/ tests/ docs/\n\n\n  python blank_remover.py src/ --space\n\n\n  python blank_remover.py . --workers 16\n\n\n  python blank_remover.py . --show-binary\n        ",
    )
    parser.add_argument(
        "directories",
        nargs="*",
        default=["."],
        help="Directories to process (default: current directory)",
    )
    parser.add_argument(
        "-s",
        "--space",
        action="store_true",
        help="Also remove lines containing only whitespace",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=os.cpu_count() or 4,
        help="Number of worker processes (default: CPU count)",
    )
    parser.add_argument(
        "--show-binary",
        action="store_true",
        help="Show all skipped binary files instead of just first 5",
    )
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color codes")
    args = parser.parse_args()
    if args.no_color or not sys.stdout.isatty():
        ANSI.disable()
    print_header()
    print_directory_list(args.directories)
    print_mode(args.space)
    print("Scanning for files... ", end="", flush=True)
    files, _skipped_dirs = discover_files(args.directories)
    print(f"Done! Found {ANSI.BOLD}{len(files):,}{ANSI.RESET} files.")
    print()
    if not files:
        print(f"{ANSI.YELLOW}No files found to process.{ANSI.RESET}\n")
        return 0
    print(f"Processing files...\n(Using {ANSI.BOLD}{args.workers}{ANSI.RESET} worker processes)\n")
    stats = ProcessingStats(total_files=len(files))
    base_dirs = [Path(d).resolve() for d in args.directories]
    start_time = time.time()
    processed_count = 0
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                process_file_worker,
                base_dirs[0] if base_dirs else Path.cwd(),
                file_path,
                args.space,
            ): file_path
            for file_path in files
        }
        for future in as_completed(futures):
            result = future.result()
            stats.results.append(result)
            processed_count += 1
            print_progress(processed_count, len(files))
            if result.status == "processed":
                stats.files_modified += 1
                stats.lines_removed += result.removed_lines
                stats.text_files += 1
            elif result.status == "unchanged":
                stats.text_files += 1
            elif result.status == "skipped_binary":
                stats.binary_files += 1
            elif result.status == "error":
                stats.errors_count += 1
    elapsed = time.time() - start_time
    print("\r" + " " * 40 + "\r", end="")
    print(
        f"  {ANSI.GREEN}Progress: Complete!{ANSI.RESET} ({ANSI.BOLD}{stats.text_files:,}{ANSI.RESET} text, {ANSI.BOLD}{
            stats.binary_files:,}{ANSI.RESET} binary)"
    )
    print_separator()
    print_results(stats, base_dirs)
    print_summary(stats)
    print(f"Completed in {ANSI.DIM}{elapsed:.2f}s{ANSI.RESET}\n")
    return 0 if stats.errors_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
