"""
Custom JSON formatter for dictionary-of-lists structures.

Usage:
    python json_formatter.py file1.json file2.json
    python json_formatter.py /path/to/dir
    python json_formatter.py            # formats all .json files in current dir recursively

Features:
    - Uses pathlib for all filesystem operations
    - Parallel processing with multiprocessing.Pool.imap_unordered (8 workers)
    - Accepts files or directories as input
    - Recursively discovers .json files when no input is provided
    - Updates files in place only when content actually changes
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import sys
from pathlib import Path
from typing import Any, Iterator
from dh import cprint


WORKERS = 8


def format_dictionary_of_lists(data: dict[str, list[str]], indent: int = 2) -> str:
    """
    Specialized formatter for the dictionary-of-lists structure:
    {
      "Abel": ["هابيل"],
      "Abelicea": ["ابلیسه"],
      ...
    }

    Each key-value pair is placed on its own line for readability.
    """
    if not data:
        return "{}"

    lines = ["{"]
    items = list(data.items())

    for i, (key, value) in enumerate(items):
        comma = "," if i < len(items) - 1 else ""
        indent_str = " " * indent
        lines.append(
            f"{indent_str}{json.dumps(key, ensure_ascii=False)}: "
            f"{json.dumps(value, ensure_ascii=False)}{comma}"
        )

    lines.append("}")
    return "\n".join(lines)


def format_json(data: Any, indent: int = 2, compact: bool = False) -> str:
    """Format JSON data with standard json.dumps."""
    if compact:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    return json.dumps(
        data,
        ensure_ascii=False,
        indent=indent,
        separators=(",", ": "),
    )


def is_dictionary_of_lists(data: Any) -> bool:
    """Check if the JSON structure matches the dictionary-of-lists pattern."""
    return isinstance(data, dict) and all(
        isinstance(value, list) for value in data.values()
    )


def process_file(
    file_path: Path, indent: int = 2, compact: bool = False
) -> tuple[Path, bool, str]:
    """
    Process a single JSON file. Returns (path, changed, message).

    This function is designed to be picklable for multiprocessing.
    """
    try:
        with file_path.open("r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)
    except json.JSONDecodeError as error:
        return file_path, False, f"Invalid JSON: {error}"
    except OSError as error:
        return file_path, False, f"Cannot read: {error}"

    # Only format files that match the dictionary-of-lists structure
    if not is_dictionary_of_lists(data):
        return file_path, False, "Structure does not match; skipped"

    formatted = format_dictionary_of_lists(data, indent)

    # Read the original file content to compare with the formatted output
    try:
        original_content = file_path.read_text(encoding="utf-8")
    except OSError as error:
        return file_path, False, f"Cannot read: {error}"

    # Only write if the content has actually changed
    if formatted == original_content:
        return file_path, False, "No Change"

    try:
        file_path.write_text(formatted, encoding="utf-8")
        return file_path, True, "Formatted"
    except OSError as error:
        return file_path, False, f"Cannot write: {error}"


def process_file_wrapper(args: tuple[Path, int, bool]) -> tuple[Path, bool, str]:
    """Wrapper to unpack arguments for imap_unordered."""
    file_path, indent, compact = args
    return process_file(file_path, indent, compact)


def discover_json_files(paths: list[Path]) -> list[Path]:
    """
    Discover .json files from given paths.

    - If a path is a file, include it if it ends with .json
    - If a path is a directory, recursively find all .json files
    - If no paths given, recursively scan current directory
    """
    json_files: list[Path] = []

    if not paths:
        paths = [Path.cwd()]

    for path in paths:
        if path.is_file():
            if path.suffix.lower() == ".json":
                json_files.append(path)
        elif path.is_dir():
            json_files.extend(path.rglob("*.json"))
        else:
            print(f"Warning: {path} does not exist; skipping", file=sys.stderr)

    # Remove duplicates while preserving order
    return list(dict.fromkeys(json_files))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Custom JSON formatter for dictionary-of-lists structures"
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="JSON files or directories (default: current directory, recursive)",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="Number of spaces for indentation (default: 2)",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Produce compact output",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=WORKERS,
        help=f"Number of parallel workers (default: {WORKERS})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be formatted without modifying files",
    )

    args = parser.parse_args()

    json_files = discover_json_files(args.paths)

    if not json_files:
        print("No .json files found.", file=sys.stderr)
        return 0

    print(f"Found {len(json_files)} JSON file(s) to process.")

    if args.dry_run:
        for file_path in json_files:
            try:
                with file_path.open("r", encoding="utf-8") as file_handle:
                    data = json.load(file_handle)
                if is_dictionary_of_lists(data):
                    print(f"Would format: {file_path}")
                else:
                    print(f"Would skip (structure mismatch): {file_path}")
            except (json.JSONDecodeError, OSError) as error:
                print(f"Would skip (error): {file_path} — {error}")
        return 0

    # Prepare task arguments
    tasks = [(file_path, args.indent, args.compact) for file_path in json_files]

    # Process files in parallel with fixed worker count
    formatted_count = 0
    skipped_count = 0
    error_count = 0

    with multiprocessing.Pool(processes=args.workers) as pool:
        # imap_unordered streams results as they complete, without preserving order
        for file_path, changed, message in pool.imap_unordered(
            process_file_wrapper, tasks
        ):
            if changed:
                formatted_count += 1
                print(f"✓ {file_path.name}: {message}")
            elif "skipped" in message.lower():
                skipped_count += 1
                print(f"  {file_path.name}: {message}")
            else:
                error_count += 1
                cprint(f"✗ {file_path.name}: {message}", file=sys.stderr)

    print(
        f"\nSummary: {formatted_count} formatted, {skipped_count} skipped, {error_count} errors"
    )

    return 1 if error_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
change above code to use ijson and mmap 
for files larger than 1mb
as described below:

import ijson

def process_large_file(file_path: Path):
    """Process a large JSON file using streaming to avoid memory issues."""
    with file_path.open("rb") as f:
        # Stream through each key-value pair
        parser = ijson.kvitems(f, '')
        for key, value in parser:
            # Process each entry one at a time
            if isinstance(value, list):
                # Your transliteration detection logic here
                pass


------------
import mmap

def read_large_file(file_path: Path):
    """Use memory mapping for efficient large file access."""
    with file_path.open("r+") as f:
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            # Process the memory-mapped content
            content = mm.read().decode('utf-8')
            # Your processing logic here
