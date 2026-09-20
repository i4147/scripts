
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
    if not data:
        return "{}"

    lines = ["{"]
    items = list(data.items())

    for i, (key, value) in enumerate(items):
        comma = "," if i < len(items) - 1 else ""
        indent_str = " " * indent
        lines.append(
            f"{indent_str}{json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_ascii=False)}{comma}"
        )

    lines.append("}")
    return "\n".join(lines)


def format_json(data: Any, indent: int = 2, compact: bool = False) -> str:
    if compact:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    return json.dumps(
        data,
        ensure_ascii=False,
        indent=indent,
        separators=(",", ": "),
    )


def is_dictionary_of_lists(data: Any) -> bool:
    return isinstance(data, dict) and all(isinstance(value, list) for value in data.values())


def process_file(file_path: Path, indent: int = 2, compact: bool = False) -> tuple[Path, bool, str]:
    try:
        with file_path.open("r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)
    except json.JSONDecodeError as error:
        return file_path, False, f"Invalid JSON: {error}"
    except OSError as error:
        return file_path, False, f"Cannot read: {error}"

    
    if not is_dictionary_of_lists(data):
        return file_path, False, "Structure does not match; skipped"

    formatted = format_dictionary_of_lists(data, indent)
    if formatted == data:
        return file_path, False, f"No Change"
    try:
        file_path.write_text(formatted, encoding="utf-8")
        return file_path, True, "Formatted"
    except OSError as error:
        return file_path, False, f"Cannot write: {error}"


def process_file_wrapper(args: tuple[Path, int, bool]) -> tuple[Path, bool, str]:
    file_path, indent, compact = args
    return process_file(file_path, indent, compact)


def discover_json_files(paths: list[Path]) -> list[Path]:
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

    
    return list(dict.fromkeys(json_files))


def main() -> int:
    parser = argparse.ArgumentParser(description="Custom JSON formatter for dictionary-of-lists structures")
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

    
    tasks = [(file_path, args.indent, args.compact) for file_path in json_files]

    
    formatted_count = 0
    skipped_count = 0
    error_count = 0

    with multiprocessing.Pool(processes=args.workers) as pool:
        
        for file_path, changed, message in pool.imap_unordered(process_file_wrapper, tasks):
            if changed:
                formatted_count += 1
                print(f"✓ {file_path.name}: {message}")
            elif "skipped" in message.lower():
                skipped_count += 1
                print(f"  {file_path.name}: {message}")
            else:
                error_count += 1
                cprint(f"✗ {file_path.name}: {message}", file=sys.stderr)

    print(f"\nSummary: {formatted_count} formatted, {skipped_count} skipped, {error_count} errors")

    return 1 if error_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
