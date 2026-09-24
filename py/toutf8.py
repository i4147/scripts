from __future__ import annotations

import argparse
import sys
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import chardet
from dh import get_nobinary, is_binary


def detect_encoding(path: Path) -> str:
    try:
        with open(path, "rb") as f:
            raw_data = f.read(100000)
            result = chardet.detect(raw_data)
            return result.get("encoding", "utf-8") or "utf-8"
    except Exception:
        return "utf-8"


def convert_file(path: Path) -> tuple[Path, bool, str]:
    try:
        if is_binary(path):
            return path, False, "Skipped (binary/unsupported)"
        encoding = detect_encoding(path)
        if encoding and encoding.lower() == "utf-8":
            return path, True, "Already UTF8"
        with open(path, "r", encoding=encoding, errors="replace") as f:
            content = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path, True, f"Converted from {encoding}"
    except Exception as e:
        return path, False, f"Error: {e!s}"


def collect_files(paths: list[str | Path]) -> Generator[Path, None, None]:
    for path_str in paths:
        path = Path(path_str).resolve()
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from path.rglob("*")
        else:
            print(f"⚠ Warning: {path} not found", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Convert non-UTF8 files to UTF8 encoding (in-place)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
        "  python script.py                    # Process current directory\n"
        "  python script.py ./src ./docs       # Process specific directories\n"
        "  python script.py file.txt dir/      # Process file and directory",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Files or directories to process (default: current directory)",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed output for each file",
    )
    args = parser.parse_args()
    input_paths = args.paths if args.paths else ["."]
    cwd = Path.cwd()
    files = get_nobinary(cwd)
    print(f"Processing {len(files)} file(s) with {args.workers} worker(s)...\n")
    converted = 0
    skipped = 0
    errors = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(convert_file, f): f for f in files}
        for future in as_completed(futures):
            path, success, message = future.result()
            if args.verbose:
                status = "✓" if success else "✗"
                print(f"{status} {path.relative_to(Path.cwd())} - {message}")
            if success:
                if "Already UTF8" in message or "Skipped" in message:
                    skipped += 1
                else:
                    converted += 1
            else:
                errors += 1
    print(f"\n{'=' * 40}")
    print("Summary:")
    print(f"  Converted: {converted}")
    print(f"  Skipped:   {skipped}")
    print(f"  Errors:    {errors}")
    print(f"{'=' * 40}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
