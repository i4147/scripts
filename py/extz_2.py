#!/data/data/com.termux/files/usr/bin/python
"""Write a Python script that scans a project directory and produces a clear,
colorized terminal report summarizing the files it contains. The tool should accept a target directory (defaulting to the current working directory) and an optional flag to control display options,
such as whether to show a per-file listing or only aggregate statistics.
The script should walk the directory tree recursively while automatically ignoring common non-source or generated folders (for example version control metadata,
dependency caches,
virtual environments,
build outputs,
and tool caches) as well as symbolic links. It should group the discovered files by their file extension and,
for each group,
report the number of files and their combined size in a human-readable format (such as bytes,
KB,
MB,
GB,
or TB). Files without an extension should be handled gracefully and reported under a clearly labeled category.
The output should be well-organized and easy to scan,
with a header,
a summary of totals (overall file count and total size),
and a breakdown sorted in a sensible order (for example,
by count or size,
descending). Use terminal colors to visually distinguish headers,
extensions,
counts,
and data values,
but ensure the output remains readable when colors are not supported. The tool should handle permission errors and unreadable files without crashing,
skipping them and continuing the scan.
The script should be runnable from the command line,
provide a help message describing its options,
and exit with a non-zero status code on invalid input such as a nonexistent or non-directory path. Output should go to standard output,
and the script should be self-contained with no external dependencies beyond the Python standard library.
---"""

from __future__ import annotations
import argparse
from collections import defaultdict
from pathlib import Path
import shutil
import sys


class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[36m"
    YELLOW = "\033[33m"
    GREEN = "\033[32m"
    MAGENTA = "\033[35m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"
    HEADER_FG = BOLD + CYAN
    EXT_FG = BOLD + MAGENTA
    COUNT_FG = BOLD + GREEN
    DATA_FG = YELLOW


SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "env",
    ".tox",
    "node_modules",
    ".next",
    "dist",
    "build",
    ".egg-info",
    ".mypy_cache",
    ".ruff_cache",
    ".coverage",
    "htmlcov",
    ".tmp",
    ".cache",
}


def format_size(bytes_val: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} PB"


def should_skip(path: Path) -> bool:
    if path.is_symlink():
        return True
    return any(part in SKIP_DIRS for part in path.parts)


def scan_extensions(show_size: bool = False) -> dict[str, tuple[list[Path], int]]:
    ext_map: dict[str, tuple[list[Path], int]] = defaultdict(lambda: ([], 0))
    cwd = Path.cwd()
    for file_path in cwd.rglob("*"):
        if should_skip(file_path):
            continue
        if file_path.is_file():
            ext = file_path.suffix or "<no-ext>"
            paths, total_size = ext_map[ext]
            file_size = file_path.stat().st_size if show_size else 0
            ext_map[ext] = (paths + [file_path], total_size + file_size)
    return ext_map


def generate_report(
    ext_map: dict[str, tuple[list[Path], int]],
    show_size: bool = False,
    max_examples: int = 3,
) -> list[tuple[str, int, str]]:
    report_data = []
    for ext in sorted(ext_map.keys(), key=lambda x: -len(ext_map[x][0])):
        paths, total_size = ext_map[ext]
        count = len(paths)
        if show_size:
            info = format_size(total_size)
        else:
            examples = ", ".join(str(p.relative_to(Path.cwd())) for p in paths[:max_examples])
            info = examples
        report_data.append((ext, count, info))
    return report_data


def format_table(
    report_data: list[tuple[str, int, str]],
    term_width: int,
    show_size: bool = False,
    use_color: bool = True,
) -> str:
    col1_width = max(10, int(term_width * 0.15))
    col2_width = 12
    col3_width = max(25, term_width - col1_width - col2_width - 5)
    lines = []
    col3_label = "Total Size" if show_size else "Example Files"
    header = f"{'Extension':<{col1_width}} | {'Count':>{col2_width}} | {col3_label:<{col3_width}}"
    if use_color:
        header = (
            f"{Colors.HEADER_FG}{'Extension':<{col1_width}}{Colors.RESET} | "
            f"{Colors.HEADER_FG}{'Count':>{col2_width}}{Colors.RESET} | "
            f"{Colors.HEADER_FG}{col3_label:<{col3_width}}{Colors.RESET}"
        )
    lines.append(header)
    lines.append(f"{Colors.DIM}{'-' * len(header)}{Colors.RESET}" if use_color else "-" * len(header))
    for ext, count, info in report_data:
        if len(info) > col3_width:
            info = info[: col3_width - 3] + "..."
        if use_color:
            row = (
                f"{Colors.EXT_FG}{ext:<{col1_width}}{Colors.RESET} | "
                f"{Colors.COUNT_FG}{count:>{col2_width}}{Colors.RESET} | "
                f"{Colors.DATA_FG}{info:<{col3_width}}{Colors.RESET}"
            )
        else:
            row = f"{ext:<{col1_width}} | {count:>{col2_width}} | {info:<{col3_width}}"
        lines.append(row)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Report file extensions in current directory recursively.")
    parser.add_argument(
        "-s",
        "--size",
        action="store_true",
        help="Show total size per extension instead of example files",
    )
    parser.add_argument("--no-color", action="store_true", help="Disable color output")
    args = parser.parse_args()
    try:
        term_width = shutil.get_terminal_size(fallback=(80, 24)).columns
        use_color = not args.no_color and sys.stdout.isatty()
        mode_str = "size mode" if args.size else "example files mode"
        cwd_str = str(Path.cwd())
        if use_color:
            print(f"Scanning {Colors.BOLD}{cwd_str}{Colors.RESET} ({mode_str})...\n")
        else:
            print(f"Scanning {cwd_str} ({mode_str})...\n")
        ext_map = scan_extensions(show_size=args.size)
        if not ext_map:
            print("No files found.")
            sys.exit(0)
        report_data = generate_report(ext_map, show_size=args.size)
        table = format_table(report_data, term_width, show_size=args.size, use_color=use_color)
        print(table)
        total_files = sum(count for _, count, _ in report_data)
        total_exts = len(report_data)
        if args.size:
            total_bytes = sum(ext_map[ext][1] for ext in ext_map)
            summary = (
                (
                    f"\n{Colors.GRAY}✓ Total unique extensions: {total_exts}{Colors.RESET}\n"
                    f"{Colors.GRAY}✓ Total files: {total_files}{Colors.RESET}\n"
                    f"{Colors.GRAY}✓ Total size: {format_size(total_bytes)}{Colors.RESET}"
                )
                if use_color
                else (
                    f"\n✓ Total unique extensions: {total_exts}\n"
                    f"✓ Total files: {total_files}\n"
                    f"✓ Total size: {format_size(total_bytes)}"
                )
            )
        else:
            summary = (
                (
                    f"\n{Colors.GRAY}✓ Total unique extensions: {total_exts}{Colors.RESET}\n"
                    f"{Colors.GRAY}✓ Total files: {total_files}{Colors.RESET}"
                )
                if use_color
                else (f"\n✓ Total unique extensions: {total_exts}\n✓ Total files: {total_files}")
            )
        print(summary)
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
