#!/data/data/com.termux/files/usr/bin/python
"""Write a Python script that acts as a command-line tool for scanning a directory tree and cleaning up files by removing unwanted lines,
with parallel processing for speed. The tool should accept a target directory (or file path) as its main input,
along with options to control behavior such as a dry-run mode that only reports what would change,
a verbose or quiet output setting,
and the ability to exclude certain paths or file types. It should automatically detect and skip binary files and any files or directories that match standard exclusion rules,
so that only text-based source content is processed.
For each eligible file,
the tool should count the total number of lines and determine how many lines would be or were removed according to the cleaning rules. Processing should happen concurrently across a configurable pool of worker processes,
with results gathered and summarized at the end. Errors encountered while reading or writing an individual file should be recorded against that file without stopping the overall run.
The final output should be a clear,
color-coded terminal report that shows per-file statistics for files that changed,
a preview of a limited number of affected files,
and overall totals including the number of files scanned,
files modified,
lines removed,
files skipped,
errors encountered,
and the total elapsed time. Colored output should be automatically disabled when the terminal does not support it or when the user requests plain output. Logging of progress and problems should be handled through a structured logging facility,
with the verbosity adjustable from the command line.
The tool should exit with a non-zero status code when fatal errors occur or when the run is invoked in a mode that expects no changes but changes are detected,
and zero otherwise. Design the solution so it is safe by default (dry-run unless explicitly told to write),
robust against unusual file encodings,
and easy to extend with additional cleaning rules.
---"""

from __future__ import annotations
import argparse
from dataclasses import dataclass, field
from multiprocessing import Pool
from pathlib import Path
import sys
import time
from typing import TYPE_CHECKING, Final
from dh import is_binary, should_skip
from loguru import logger

if TYPE_CHECKING:
    from multiprocessing.pool import AsyncResult
ANSI_RESET: Final[str] = "\x1b[0m"
ANSI_BOLD: Final[str] = "\x1b[1m"
ANSI_DIM: Final[str] = "\x1b[2m"
ANSI_CYAN: Final[str] = "\x1b[36m"
ANSI_GREEN: Final[str] = "\x1b[32m"
ANSI_YELLOW: Final[str] = "\x1b[33m"
ANSI_RED: Final[str] = "\x1b[31m"
NUM_WORKERS: Final[int] = 8
MAX_PREVIEW_FILES: Final[int] = 5


class ANSI:
    RESET: str = ANSI_RESET
    BOLD: str = ANSI_BOLD
    DIM: str = ANSI_DIM
    CYAN: str = ANSI_CYAN
    GREEN: str = ANSI_GREEN
    YELLOW: str = ANSI_YELLOW
    RED: str = ANSI_RED

    @classmethod
    def disable(cls) -> None:
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


def remove_blank_lines(path: Path, remove_spaces: bool = False) -> tuple[int, int]:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except OSError as e:
        msg = f"Failed to read file: {e}"
        raise OSError(msg)
    total_lines: int = len(lines)
    if remove_spaces:
        filtered: list[str] = [line for line in lines if line.strip()]
    else:
        filtered = [line for line in lines if line not in ("\n", "\r\n", "\r")]
    removed_lines: int = total_lines - len(filtered)
    if removed_lines > 0:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(filtered)
        except OSError as e:
            msg = f"Failed to write file: {e}"
            raise OSError(msg)
    return (total_lines, removed_lines)


def process_file_worker(path: Path, remove_spaces: bool = False) -> FileResult:
    result: FileResult = FileResult(path=path, status="error")
    try:
        try:
            with open(path, "rb") as f:
                first_8kb: bytes = f.read(8192)
        except OSError:
            result.status = "error"
            result.error_message = "Permission denied"
            return result
        if is_binary(path):
            result.status = "skipped_binary"
            result.is_bin = True
            return result
        total_lines, removed_lines = remove_blank_lines(path, remove_spaces)
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
    files: list[Path] = []
    skipped_dirs: int = 0
    for dir_str in directories:
        dir_path = Path(dir_str).resolve()
        if not dir_path.exists():
            logger.warning(f"Directory not found: {dir_path}")
            skipped_dirs += 1
            continue
        if not dir_path.is_dir():
            logger.warning(f"Not a directory: {dir_path}")
            skipped_dirs += 1
            continue
        for path in dir_path.rglob("*"):
            if path.is_file() and not should_skip(path):
                files.append(path)
    return (files, skipped_dirs)


def print_directory_list(directories: list[str]) -> None:
    print("Processing directories:")
    for dir_str in directories:
        print(f"  {ANSI.DIM}•{ANSI.RESET} {Path(dir_str).resolve()}")


def print_mode(remove_spaces: bool) -> None:
    if remove_spaces:
        print(f"Mode: {ANSI.BOLD}Remove blank lines and whitespace-only lines{ANSI.RESET}")
    else:
        print(f"Mode: {ANSI.BOLD}Remove blank lines only{ANSI.RESET}")


def print_separator() -> None:
    print(f"{ANSI.CYAN}{'─' * 40}{ANSI.RESET}")


def print_results(stats: ProcessingStats, show_binary: bool = False) -> None:
    processed: list[FileResult] = [r for r in stats.results if r.status == "processed"]
    unchanged: list[FileResult] = [r for r in stats.results if r.status == "unchanged"]
    skipped_binary: list[FileResult] = [r for r in stats.results if r.status == "skipped_binary"]
    errors: list[FileResult] = [r for r in stats.results if r.status == "error"]
    if processed:
        print(f"{ANSI.GREEN}✓ Modified files:{ANSI.RESET}")
        for result in sorted(processed, key=lambda r: r.path):
            try:
                rel_path = result.path.relative_to(Path.cwd())
            except ValueError:
                rel_path = result.path
            print(f"  {ANSI.GREEN}●{ANSI.RESET} {rel_path}")
            print(f"    {ANSI.DIM}Lines: {result.total_lines}  →  Removed: {result.removed_lines}{ANSI.RESET}")
    if unchanged:
        print(f"{ANSI.DIM}○ Unchanged files (no blank lines):{ANSI.RESET}")
        for result in sorted(unchanged, key=lambda r: r.path)[:MAX_PREVIEW_FILES]:
            try:
                rel_path = result.path.relative_to(Path.cwd())
            except ValueError:
                rel_path = result.path
            print(f"  {ANSI.DIM}○ {rel_path}{ANSI.RESET}")
        if len(unchanged) > MAX_PREVIEW_FILES:
            print(f"  {ANSI.DIM}... and {len(unchanged) - MAX_PREVIEW_FILES} more{ANSI.RESET}")
    if skipped_binary:
        print(f"{ANSI.YELLOW}⊘ Skipped binary files: {len(skipped_binary)}{ANSI.RESET}")
        preview: list[FileResult] = (
            skipped_binary if show_binary else sorted(skipped_binary, key=lambda r: r.path)[:MAX_PREVIEW_FILES]
        )
        for result in sorted(preview, key=lambda r: r.path):
            try:
                rel_path = result.path.relative_to(Path.cwd())
            except ValueError:
                rel_path = result.path
            print(f"  {ANSI.YELLOW}⊘ {rel_path}{ANSI.RESET}")
        if not show_binary and len(skipped_binary) > MAX_PREVIEW_FILES:
            print(f"  {ANSI.YELLOW}... and {len(skipped_binary) - MAX_PREVIEW_FILES} more binary files{ANSI.RESET}")
    if errors:
        print(f"{ANSI.RED}✗ Errors:{ANSI.RESET}")
        for result in sorted(errors, key=lambda r: r.path):
            try:
                rel_path = result.path.relative_to(Path.cwd())
            except ValueError:
                rel_path = result.path
            logger.error(f"  {ANSI.RED}✗ {rel_path}{ANSI.RESET}")
            logger.error(f"    {ANSI.DIM}{result.error_message}{ANSI.RESET}")


def print_summary(stats: ProcessingStats) -> None:
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recursively remove blank lines from text files with parallel processing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\nExamples:\n\n  python blank_remover.py\n\n\n  python blank_remover.py src/ tests/ docs/\n\n\n  python blank_remover.py src/ --space\n\n\n  python blank_remover.py . --show-binary\n        ",
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
        "--show-binary",
        action="store_true",
        help="Show all skipped binary files instead of just first 5",
    )
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color codes")
    args = parser.parse_args()
    if args.no_color or not sys.stdout.isatty():
        ANSI.disable()
    print_directory_list(args.directories)
    print_mode(args.space)
    print("Scanning for files... ")
    files, _skipped_dirs = discover_files(args.directories)
    print(f"Done! Found {ANSI.BOLD}{len(files):,}{ANSI.RESET} files.")
    if not files:
        logger.warning(f"{ANSI.YELLOW}No files found to process.{ANSI.RESET}")
        return 0
    print(f"Processing files...\n(Using {ANSI.BOLD}{NUM_WORKERS}{ANSI.RESET} worker processes)")
    stats: ProcessingStats = ProcessingStats(total_files=len(files))
    start_time: float = time.time()
    processed_count: int = 0
    with Pool(processes=NUM_WORKERS) as pool:
        async_results: list[AsyncResult[FileResult]] = []
        for path in files:
            async_result: AsyncResult[FileResult] = pool.apply_async(process_file_worker, (path, args.space))
            async_results.append(async_result)
        for async_result in async_results:
            result: FileResult = async_result.get()
            stats.results.append(result)
            processed_count += 1
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
    elapsed: float = time.time() - start_time
    print(
        f"  {ANSI.GREEN}Progress: Complete!{ANSI.RESET} ({ANSI.BOLD}{stats.text_files:,}{ANSI.RESET} text, {ANSI.BOLD}{stats.binary_files:,}{ANSI.RESET} binary)"
    )
    print_separator()
    print_results(stats, args.show_binary)
    print_summary(stats)
    print(f"Completed in {ANSI.DIM}{elapsed:.2f}s{ANSI.RESET}")
    return 0 if stats.errors_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
