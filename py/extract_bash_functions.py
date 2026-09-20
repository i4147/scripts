from __future__ import annotations

import argparse
import contextlib
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from fastwalk import walk_files

EXCLUDED = {
    ".py",
    ".h",
    ".c",
    ".js",
    ".ts",
    ".hpp",
    ".cpp",
    ".pyx",
    ".jsx",
    ".lua",
    ".tsx",
    ".pl",
    ".am",
    ".pm",
    ".syntax",
}
IS_TERMUX = os.environ.get("TERMUX_VERSION") is not None or "com.termux" in os.environ.get("PREFIX", "")
DEFAULT_WORKERS = 6 if IS_TERMUX else 8


def is_bash_script(file_path: Path) -> bool:
    if file_path.suffix == ".sh":
        return True
    if not file_path.is_file():
        return False
    try:
        if file_path.stat().st_size > 1000000:
            return False
    except OSError:
        return False
    try:
        with open(file_path, "rb") as f:
            first_bytes = f.read(2)
            if b"\x00" in first_bytes:
                return False
            f.seek(0)
            first_line = f.readline().decode("utf-8", errors="ignore").strip()
            if first_line.startswith("#!"):
                shell_patterns = ["bash", "sh", "dash", "ksh", "zsh", "ash", "shell"]
                shebang_lower = first_line.lower()
                if any(shell in shebang_lower for shell in shell_patterns):
                    return True
    except (OSError, UnicodeDecodeError):
        return False
    return False


def find_sh_files(paths: list[Path], include_extensionless: bool = True) -> set[Path]:
    sh_files = set()
    for path in paths:
        if not path.exists():
            print(f"Warning: {path} does not exist, skipping...", file=sys.stderr)
            continue
        if path.is_file():
            if is_bash_script(path):
                sh_files.add(path.resolve())
        elif path.is_dir():
            for item in walk_files(path):
                item = Path(item)
                if item.suffix in EXCLUDED:
                    continue
                if item.is_file() and is_bash_script(item):
                    sh_files.add(item.resolve())
        else:
            print(
                f"Warning: {path} is not a file or directory, skipping...",
                file=sys.stderr,
            )
    return sh_files


def extract_functions_from_file(sh_file: Path) -> list[tuple[str, str, Path]]:
    try:
        with open(sh_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {sh_file}: {e}", file=sys.stderr)
        return []
    functions = []
    lines = content.split("\n")
    function_start_pattern = re.compile("^\\s*(?:function\\s+)?(\\w[\\w\\-]*)\\s*(?:\\(\\))?\\s*\\{")
    i = 0
    while i < len(lines):
        line = lines[i]
        match = function_start_pattern.match(line)
        if match:
            func_name = match.group(1)
            func_lines = [line]
            brace_count = line.count("{") - line.count("}")
            j = i + 1
            while j < len(lines) and brace_count > 0:
                current_line = lines[j]
                func_lines.append(current_line)
                brace_count += current_line.count("{") - current_line.count("}")
                j += 1
            if brace_count == 0:
                function_content = "\n".join(func_lines)
                functions.append((func_name, function_content, sh_file))
            else:
                print(
                    f"Warning: Could not find matching closing brace for function '{func_name}' in {sh_file}",
                    file=sys.stderr,
                )
            i = j
        else:
            i += 1
    return functions


def process_file(sh_file: Path, output_dir: Path, use_extension: bool = True) -> list[tuple[str, Path]]:
    functions = extract_functions_from_file(sh_file)
    saved_functions = []
    for func_name, func_content, source_file in functions:
        safe_func_name = re.sub(r"[^\w\-]", "_", func_name)
        try:
            rel_path = source_file.relative_to(Path.cwd())
        except ValueError:
            rel_path = source_file
        func_output_dir = output_dir / rel_path.parent
        if use_extension:
            output_file = func_output_dir / f"{safe_func_name}.sh"
        else:
            output_file = func_output_dir / safe_func_name
        func_output_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(func_content)
                f.write("\n")
            saved_functions.append((func_name, output_file))
        except Exception as e:
            print(
                f"Error writing function '{func_name}' to {output_file}: {e}",
                file=sys.stderr,
            )
    return saved_functions


def get_optimal_workers() -> int:
    return DEFAULT_WORKERS


def main():
    parser = argparse.ArgumentParser(
        description="Extract functions from shell scripts (.sh and extensionless) recursively",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\nExamples:\n  # Process all shell scripts in current directory recursively\n  %(prog)s\n  \n  # Process specific files and directories\n  %(prog)s script1.sh myscript dir1/ dir2/\n  \n  # Specify output directory and number of workers\n  %(prog)s -o extracted_functions -w 4 dir1/ dir2/\n  \n  # Only process .sh files (ignore extensionless scripts)\n  %(prog)s --sh-only\n  \n  # In Termux, this is automatically detected\n  %(prog)s ~/storage/shared/scripts/\n        ",
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help="Files and/or directories to process. If none provided, processes all shell scripts in current directory recursively.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("extracted_functions"),
        help="Output directory for extracted functions (default: extracted_functions)",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=None,
        help=f"Number of parallel workers (default: auto-detected, currently {get_optimal_workers()})",
    )
    parser.add_argument(
        "--no-parallel",
        action="store_true",
        help="Disable parallel processing (process sequentially)",
    )
    parser.add_argument(
        "--sh-only",
        action="store_true",
        help="Only process files with .sh extension (ignore extensionless scripts)",
    )
    parser.add_argument(
        "--no-extension",
        action="store_true",
        help="Output functions without .sh extension",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show verbose output including skipped files",
    )
    args = parser.parse_args()
    if args.workers is None:
        args.workers = get_optimal_workers()
    if IS_TERMUX:
        print(f"Running in Termux environment (using {args.workers} workers)")
    if args.inputs:
        input_paths = args.inputs
    else:
        input_paths = [Path(".")]
    print("Searching for shell scripts...")
    include_extensionless = not args.sh_only
    sh_files = find_sh_files(input_paths, include_extensionless)
    if not sh_files:
        print("No shell scripts found to process.")
        if not args.sh_only:
            print("Tip: Use --sh-only to only process .sh files")
        return 0
    print(f"Found {len(sh_files)} shell script(s) to process:")
    if args.verbose:
        for f in sorted(sh_files):
            print(f"  - {f}")
    try:
        args.output.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        print(
            f"Error: Cannot create output directory '{args.output}'. Check permissions.",
            file=sys.stderr,
        )
        return 1
    total_functions = 0
    use_extension = not args.no_extension
    if args.no_parallel or len(sh_files) == 1:
        print("Processing files sequentially...")
        for sh_file in sorted(sh_files):
            saved = process_file(sh_file, args.output, use_extension)
            total_functions += len(saved)
            if args.verbose or saved:
                print(f"  {sh_file}: extracted {len(saved)} function(s)")
    else:
        print(f"Processing files in parallel with {args.workers} workers...")
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            future_to_file = {
                executor.submit(process_file, sh_file, args.output, use_extension): sh_file for sh_file in sh_files
            }
            for future in as_completed(future_to_file):
                sh_file = future_to_file[future]
                try:
                    saved = future.result()
                    total_functions += len(saved)
                    if args.verbose or saved:
                        print(f"  {sh_file}: extracted {len(saved)} function(s)")
                except Exception as e:
                    print(f"Error processing {sh_file}: {e}", file=sys.stderr)
    print(f"\nDone! Extracted {total_functions} function(s) to '{args.output.absolute()}'")
    if IS_TERMUX:
        with contextlib.suppress(BaseException):
            args.output.chmod(args.output.stat().st_mode | 493)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting...")
        sys.exit(1)
