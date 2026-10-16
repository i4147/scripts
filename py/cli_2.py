from __future__ import annotations

import argparse
import json
import mmap
import os
import sys
import tempfile
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import Any

MMAP_THRESHOLD = 1024 * 1024

JSON_EXTENSIONS = frozenset({".json"})

_MINIFIED_SEPARATORS = (",", ":")


def custom_format(data: Any, sort_keys: bool = False) -> str:
    if isinstance(data, dict) and data:
        items = sorted(data.items()) if sort_keys else data.items()
        inner = ",\n  ".join(
            f"{json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False, sort_keys=sort_keys)}"
            for k, v in items
        )
        return "{\n  " + inner + "\n}"

    if isinstance(data, list) and data:
        inner = ",\n  ".join(json.dumps(v, ensure_ascii=False, sort_keys=sort_keys) for v in data)
        return "[\n  " + inner + "\n]"

    return json.dumps(data, ensure_ascii=False, sort_keys=sort_keys)


def _read_text(path: Path) -> str:
    if path.stat().st_size > MMAP_THRESHOLD:
        with path.open("rb") as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                return mm.read().decode("utf-8")
    return path.read_text(encoding="utf-8")


def _atomic_write(path: Path, text: str) -> None:
    original_mode = path.stat().st_mode

    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp_path, original_mode)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def process_json_file(task: tuple[str, bool, bool]) -> tuple[str, bool, str | None]:
    file_path_str, minify, sort_keys = task
    file_path = Path(file_path_str)

    try:
        data = json.loads(_read_text(file_path))

        if minify:
            output = json.dumps(
                data,
                ensure_ascii=False,
                separators=_MINIFIED_SEPARATORS,
                sort_keys=sort_keys,
            )
        else:
            output = custom_format(data, sort_keys=sort_keys)

        _atomic_write(file_path, output + "\n")
        return (file_path_str, True, None)

    except json.JSONDecodeError as e:
        return (file_path_str, False, f"Invalid JSON: {e}")
    except OSError as e:
        return (file_path_str, False, f"I/O error: {e}")
    except Exception as e:
        return (file_path_str, False, f"Error: {e}")


def is_json_file(path: Path) -> bool:
    if path.suffix.lower() in JSON_EXTENSIONS:
        return True
    try:
        with path.open("rb") as f:
            return f.read(1) == b"{"
    except OSError:
        return False


def collect_json_files(paths: list[str], recursive: bool = True) -> set[Path]:
    found: set[Path] = set()
    glob_pat = "**/*" if recursive else "*"

    for raw in paths:
        p = Path(raw)
        if p.is_file():
            found.add(p)
        elif p.is_dir():
            for child in p.glob(glob_pat):
                if child.is_file() and is_json_file(child):
                    found.add(child)

    return found


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prettify or minify JSON files with multiprocessing support",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  jb
  jb file.json
  jb .prettierrc
  jb -m file.json
  jb -s dir/
  jb -m -s file.json
  jb file1.json dir1/
        """,
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "-b",
        "--beautify",
        action="store_true",
        help="Beautify/prettify JSON (default)",
    )
    mode_group.add_argument(
        "-m",
        "--minify",
        action="store_true",
        help="Minify JSON (remove whitespace)",
    )

    parser.add_argument(
        "-s",
        "--sort-keys",
        action="store_true",
        help="Sort object keys alphabetically (default: off)",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=None,
        help="JSON files or directories (default: current directory)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help=f"Number of worker processes (default: CPU count = {cpu_count()})",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    paths = args.paths or ["."]
    minify = args.minify

    json_files = collect_json_files(paths, recursive=True)
    if not json_files:
        print("No JSON files found.", file=sys.stderr)
        return 1

    process_args = [(str(f), minify, args.sort_keys) for f in sorted(json_files)]

    workers = min(args.workers or cpu_count(), len(process_args))
    workers = max(workers, 1)

    mode_text = "Minifying" if minify else "Prettifying"
    sort_text = " with sorted keys" if args.sort_keys else ""
    print(f"Processing {len(json_files)} JSON file(s) using {workers} worker(s)...")
    print(f"{mode_text}{sort_text}...")

    with Pool(processes=workers) as pool:
        results = pool.map(process_json_file, process_args)

    success_count = 0
    error_count = 0
    for file_path, ok, error in results:
        if ok:
            success_count += 1
        else:
            error_count += 1
            print(f"✗ {file_path}: {error}", file=sys.stderr)

    print(f"\n✓ Successfully processed: {success_count} file(s)")
    if error_count:
        print(f"✗ Failed: {error_count} file(s)")
        return 1

    print("All files processed successfully!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
