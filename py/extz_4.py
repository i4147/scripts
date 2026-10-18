#!/data/data/com.termux/files/usr/bin/python3.12
from __future__ import annotations
import argparse
import os
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Generator


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


def walk_files(root: Path | None = None, skip_dirs: set | None = None) -> Generator[tuple[Path, int], None, None]:
    if root is None:
        root = Path.cwd()
    if skip_dirs is None:
        skip_dirs = SKIP_DIRS
    dirs_to_process = [root]
    while dirs_to_process:
        current_dir = dirs_to_process.pop()
        try:
            with os.scandir(current_dir) as entries:
                for entry in entries:
                    if entry.is_symlink():
                        continue
                    if entry.name in skip_dirs:
                        continue
                    if entry.is_file(follow_symlinks=False):
                        # Yield (Path, file_size)
                        yield (Path(entry.path), entry.stat(follow_symlinks=False).st_size)
                    elif entry.is_dir(follow_symlinks=False):
                        dirs_to_process.append(Path(entry.path))
        except (PermissionError, OSError) as e:
            continue


def scan_extensions(show_size: bool = False) -> dict[str, tuple[list[Path], int]]:
    ext_map: dict[str, tuple[list[Path], int]] = defaultdict(lambda: ([], 0))
    for file_path, file_size in walk_files():
        ext = file_path.suffix or "<no-ext>"
        paths, total_size = ext_map[ext]
        ext_map[ext] = (paths + [file_path], total_size + (file_size if show_size else 0))
    return ext_map


def generate_report(
    ext_map: dict[str, tuple[list[Path], int]], show_size: bool = False, max_examples: int = 3
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
    report_data: list[tuple[str, int, str]], term_width: int, show_size: bool = False, use_color: bool = True
) -> str:
    col1_width = max(10, int(term_width * 0.15))
    col2_width = 12
    col3_width = max(25, term_width - col1_width - col2_width - 5)
    lines = []
    col3_label = "Total Size" if show_size else "Example Files"
    if use_color:
        header = (
            f"{Colors.HEADER_FG}{'Extension':<{col1_width}}{Colors.RESET} | "
            f"{Colors.HEADER_FG}{'Count':>{col2_width}}{Colors.RESET} | "
            f"{Colors.HEADER_FG}{col3_label:<{col3_width}}{Colors.RESET}"
        )
        separator = f"{Colors.DIM}{'-' * (col1_width + col2_width + col3_width + 7)}{Colors.RESET}"
    else:
        header = f"{'Extension':<{col1_width}} | {'Count':>{col2_width}} | {col3_label:<{col3_width}}"
        separator = "-" * (col1_width + col2_width + col3_width + 7)
    lines.append(header)
    lines.append(separator)
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
    parser = argparse.ArgumentParser(
        description="Report file extensions in current directory recursively (scandir-based)."
    )
    parser.add_argument(
        "-s", "--size", action="store_true", help="Show total size per extension instead of example files"
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
            if use_color:
                summary = (
                    f"\n{Colors.GRAY}✓ Total unique extensions: {total_exts}{Colors.RESET}\n"
                    f"{Colors.GRAY}✓ Total files: {total_files}{Colors.RESET}\n"
                    f"{Colors.GRAY}✓ Total size: {format_size(total_bytes)}{Colors.RESET}"
                )
            else:
                summary = (
                    f"\n✓ Total unique extensions: {total_exts}\n"
                    f"✓ Total files: {total_files}\n"
                    f"✓ Total size: {format_size(total_bytes)}"
                )
        elif use_color:
            summary = (
                f"\n{Colors.GRAY}✓ Total unique extensions: {total_exts}{Colors.RESET}\n"
                f"{Colors.GRAY}✓ Total files: {total_files}{Colors.RESET}"
            )
        else:
            summary = f"\n✓ Total unique extensions: {total_exts}\n✓ Total files: {total_files}"
        print(summary)
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
