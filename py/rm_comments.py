from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

try:
    from binaryornot.check import is_binary
except ImportError:
    print("Error: binaryornot is required. Install it with: pip install binaryornot")
    sys.exit(1)
EXCLUDE_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".so",
    ".dll",
    ".dylib",
    ".class",
    ".exe",
    ".bin",
    ".dat",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".ico",
    ".svg",
    ".mp3",
    ".mp4",
    ".avi",
    ".mov",
    ".wav",
    ".flac",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".7z",
    ".rar",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".eot",
    ".min.js",
    ".min.css",
}


def remove_comments_from_content(content: str) -> tuple[str, int]:
    lines = content.split("\n")
    modified_lines = []
    removed_count = 0
    in_multiline_string = False
    string_delimiter = None
    for line in lines:
        if in_multiline_string:
            modified_lines.append(line)
            if string_delimiter in line:
                in_multiline_string = False
            continue
        if '"""' in line or "'''" in line:
            for delim in ['"""', "'''"]:
                if delim in line:
                    if line.count(delim) % 2 == 1:
                        in_multiline_string = not in_multiline_string
                        string_delimiter = delim
                    modified_lines.append(line)
                    break
            continue
        stripped = line.strip()
        if not stripped:
            modified_lines.append(line)
            continue
        if stripped.startswith("#"):
            removed_count += 1
            modified_lines.append("")
            continue
        quote_char = None
        comment_pos = -1
        for i, char in enumerate(line):
            if char in ('"', "'"):
                if quote_char is None:
                    quote_char = char
                elif quote_char == char:
                    quote_char = None
            elif char == "#" and quote_char is None:
                comment_pos = i
                break
        if comment_pos != -1:
            before_comment = line[:comment_pos].strip()
            if before_comment:
                removed_count += 1
                modified_lines.append(line[:comment_pos].rstrip())
            else:
                removed_count += 1
                modified_lines.append("")
        else:
            modified_lines.append(line)
    return "\n".join(modified_lines), removed_count


def is_ignored_extension(file_path: Path) -> bool:
    suffix = file_path.suffix.lower()
    if suffix in EXCLUDE_EXTENSIONS:
        return True
    if len(file_path.suffixes) > 1:
        double_suffix = "".join(file_path.suffixes[-2:]).lower()
        if double_suffix in EXCLUDE_EXTENSIONS:
            return True
    return False


def is_hidden(file_path: Path) -> bool:
    return any(part.startswith(".") for part in file_path.parts)


def process_file(file_path: Path) -> tuple[Path, int, str | None, bool]:
    try:
        if is_binary(str(file_path)):
            return file_path, 0, None, True
        with open(file_path, "r", encoding="utf-8") as f:
            original_content = f.read()
        modified_content, removed_count = remove_comments_from_content(original_content)
        if removed_count > 0:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(modified_content)
        return file_path, removed_count, None, False
    except UnicodeDecodeError:
        return file_path, 0, "Unable to read as text file (encoding issue)", True
    except Exception as e:
        return file_path, 0, str(e), False


def find_target_files(
    root_dir: Path,
    include_hidden: bool = False,
    exclude_dirs: set[str] | None = None,
    ignore_extensions: bool = True,
) -> list:
    if exclude_dirs is None:
        exclude_dirs = {
            ".git",
            "__pycache__",
            "node_modules",
            ".venv",
            "venv",
            "env",
            ".env",
            "dist",
            "build",
            ".tox",
            ".eggs",
            ".idea",
            ".vscode",
            "vendor",
            "bower_components",
        }
    target_files = []
    for file_path in root_dir.rglob("*"):
        if not file_path.is_file():
            continue
        if any(excluded in file_path.parts for excluded in exclude_dirs):
            continue
        if not include_hidden and is_hidden(file_path):
            continue
        if ignore_extensions and is_ignored_extension(file_path):
            continue
        try:
            if file_path.stat().st_size > 10 * 1024 * 1024:
                continue
        except OSError:
            continue
        target_files.append(file_path)
    return target_files


def main():
    parser = argparse.ArgumentParser(description="Remove comments from non-binary files using # comment syntax")
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Root directory to process (default: current directory)",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="Include hidden files and directories (starting with .)",
    )
    parser.add_argument(
        "--no-ignore-extensions",
        action="store_true",
        help="Process files with typically ignored extensions",
    )
    parser.add_argument("--exclude-dirs", nargs="+", help="Additional directories to exclude")
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="Maximum number of parallel workers (default: CPU count)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument("--verbose", action="store_true", help="Show detailed processing information")
    args = parser.parse_args()
    root_dir = Path(args.directory).resolve()
    if not root_dir.exists():
        print(f"Error: Directory '{root_dir}' does not exist", file=sys.stderr)
        sys.exit(1)
    exclude_dirs = {
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        "env",
        ".env",
        "dist",
        "build",
        ".tox",
        ".eggs",
        ".idea",
        ".vscode",
        "vendor",
        "bower_components",
    }
    if args.exclude_dirs:
        exclude_dirs.update(args.exclude_dirs)
    print(f"Scanning directory: {root_dir}")
    print("Finding non-binary files...")
    target_files = find_target_files(
        root_dir,
        include_hidden=args.include_hidden,
        exclude_dirs=exclude_dirs,
        ignore_extensions=not args.no_ignore_extensions,
    )
    if not target_files:
        print("No files found to process.")
        return
    print(f"Found {len(target_files)} file(s) to check")
    if args.dry_run:
        print("\n[Dry Run] Would check these files:")
        for f in sorted(target_files)[:20]:
            print(f"  {f.relative_to(root_dir)}")
        if len(target_files) > 20:
            print(f"  ... and {len(target_files) - 20} more files")
        return
    total_removed = 0
    files_changed = 0
    files_with_errors = 0
    binary_files = 0
    print("\nProcessing files in parallel...")
    with ProcessPoolExecutor(max_workers=args.max_workers) as executor:
        future_to_file = {executor.submit(process_file, file_path): file_path for file_path in target_files}
        completed = 0
        for future in as_completed(future_to_file):
            file_path = future_to_file[future]
            completed += 1
            try:
                path, removed, error, was_binary = future.result()
                if was_binary:
                    binary_files += 1
                    if args.verbose:
                        print(f"[{completed}/{len(target_files)}] Skipped binary: {path.relative_to(root_dir)}")
                elif error:
                    print(f"[{completed}/{len(target_files)}] Error: {path.relative_to(root_dir)}: {error}")
                    files_with_errors += 1
                elif removed > 0:
                    print(
                        f"[{completed}/{len(target_files)}] Removed {removed} comment(s): {path.relative_to(root_dir)}"
                    )
                    total_removed += removed
                    files_changed += 1
                else:
                    if args.verbose:
                        print(f"[{completed}/{len(target_files)}] No changes: {path.relative_to(root_dir)}")
            except Exception as e:
                print(f"[{completed}/{len(target_files)}] Unexpected error: {file_path}: {e}")
                files_with_errors += 1
    print(f"\n{'=' * 40}")
    print("Summary:")
    print(f"  Files scanned: {len(target_files)}")
    print(f"  Binary files skipped: {binary_files}")
    print(f"  Files changed: {files_changed}")
    print(f"  Total comments removed: {total_removed}")
    if files_with_errors > 0:
        print(f"  Files with errors: {files_with_errors}")
    print(f"{'=' * 40}")


if __name__ == "__main__":
    raise SystemExit(main())
