
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def format_json(data: Any, indent: int = 2, compact: bool = False) -> str:
    if compact:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    return json.dumps(
        data,
        ensure_ascii=False,
        indent=indent,
        separators=(",", ": "),
    )


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


def process_file(file_path: Path, indent: int = 2, compact: bool = False) -> str:
    try:
        with file_path.open("r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {file_path}: {error}") from error
    except OSError as error:
        raise OSError(f"Cannot read {file_path}: {error}") from error

    
    if isinstance(data, dict) and all(isinstance(value, list) for value in data.values()):
        return format_dictionary_of_lists(data, indent)

    return format_json(data, indent, compact)


def main() -> int:
    parser = argparse.ArgumentParser(description="Custom JSON formatter for dictionary-of-lists structures")
    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="JSON file(s) to format",
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
        "--output",
        type=Path,
        help="Write output to file instead of stdout",
    )

    args = parser.parse_args()

    results = []
    for file_path in args.files:
        try:
            formatted = process_file(file_path, args.indent, args.compact)
            results.append(formatted)
        except (ValueError, OSError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1

    output_text = "\n".join(results)

    if args.output:
        args.output.write_text(output_text, encoding="utf-8")
    else:
        print(output_text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
