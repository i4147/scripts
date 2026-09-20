from __future__ import annotations

import argparse
import contextlib
import multiprocessing as mp
import os
import shutil
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import tree_sitter_css
from tree_sitter import Language, Parser

DEFAULT_WORKERS = 8
CSS_SUFFIXES = {".css"}
CSS_LANGUAGE = Language(tree_sitter_css.language())


def create_parser() -> Parser:
    parser = Parser(CSS_LANGUAGE)
    return parser


_PARSER: Parser | None = None


def worker_init() -> None:
    global _PARSER
    _PARSER = create_parser()


@dataclass(slots=True, frozen=True)
class ProcessResult:
    path: str
    comments_removed: int
    changed: bool
    error: str | None = None


def iter_css_files(inputs: list[Path]) -> Iterator[Path]:
    seen: set[Path] = set()
    for input_path in inputs:
        try:
            path = input_path.resolve()
        except OSError as exc:
            print(
                f"warning: cannot resolve {input_path}: {exc}",
                file=sys.stderr,
            )
            continue
        if path.is_file():
            if path.suffix.lower() in CSS_SUFFIXES and path not in seen:
                seen.add(path)
                yield path
            continue
        if not path.is_dir():
            print(
                f"warning: not a file or directory: {input_path}",
                file=sys.stderr,
            )
            continue
        try:
            for candidate in path.rglob("*"):
                if not candidate.is_file():
                    continue
                if candidate.suffix.lower() not in CSS_SUFFIXES:
                    continue
                try:
                    resolved = candidate.resolve()
                except OSError:
                    continue
                if resolved in seen:
                    continue
                seen.add(resolved)
                yield resolved
        except OSError as exc:
            print(
                f"warning: cannot scan {input_path}: {exc}",
                file=sys.stderr,
            )


def find_comment_ranges(
    source: bytes,
) -> list[tuple[int, int]]:
    global _PARSER
    if _PARSER is None:
        _PARSER = create_parser()
    tree = _PARSER.parse(source)
    ranges: list[tuple[int, int]] = []
    cursor = tree.walk()
    visited_children = False
    while True:
        node = cursor.node
        if node.type == "comment":
            ranges.append((node.start_byte, node.end_byte))
        if not visited_children and cursor.goto_first_child():
            visited_children = False
            continue
        if cursor.goto_next_sibling():
            visited_children = False
            continue
        while True:
            if not cursor.goto_parent():
                return ranges
            if cursor.goto_next_sibling():
                visited_children = False
                break
        continue


def remove_ranges(
    source: bytes,
    ranges: list[tuple[int, int]],
) -> bytes:
    if not ranges:
        return source
    removed_bytes = sum(end - start for start, end in ranges)
    output = bytearray(len(source) - removed_bytes)
    source_pos = 0
    output_pos = 0
    for start, end in ranges:
        chunk = source[source_pos:start]
        output[output_pos : output_pos + len(chunk)] = chunk
        output_pos += len(chunk)
        source_pos = end
    tail = source[source_pos:]
    output[output_pos : output_pos + len(tail)] = tail
    return bytes(output)


def atomic_replace(path: Path, data: bytes) -> None:
    directory = path.parent
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=directory,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        with contextlib.suppress(OSError):
            shutil.copymode(path, tmp_path)
        os.replace(tmp_path, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp_path.unlink(missing_ok=True)
        raise


def process_file(path_str: str) -> ProcessResult:
    path = Path(path_str)
    try:
        source = path.read_bytes()
        ranges = find_comment_ranges(source)
        if not ranges:
            return ProcessResult(
                path=str(path),
                comments_removed=0,
                changed=False,
            )
        cleaned = remove_ranges(source, ranges)
        if cleaned == source:
            return ProcessResult(
                path=str(path),
                comments_removed=0,
                changed=False,
            )
        atomic_replace(path, cleaned)
        return ProcessResult(
            path=str(path),
            comments_removed=len(ranges),
            changed=True,
        )
    except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
        return ProcessResult(
            path=str(path),
            comments_removed=0,
            changed=False,
            error=f"{type(exc).__name__}: {exc}",
        )
    except Exception as exc:
        return ProcessResult(
            path=str(path),
            comments_removed=0,
            changed=False,
            error=f"{type(exc).__name__}: {exc}",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Strip CSS comments using tree-sitter.",
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        metavar="PATH",
        help=(
            "CSS files/directories to process. Directories are searched recursively. Defaults to the current directory."
        ),
    )
    parser.add_argument(
        "-j",
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        metavar="N",
        help=f"number of worker processes (default: {DEFAULT_WORKERS})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.workers < 1:
        print(
            "error: --workers must be >= 1",
            file=sys.stderr,
        )
        return 2
    inputs = args.inputs or [Path.cwd()]
    files = iter_css_files(inputs)
    total_files = 0
    changed_files = 0
    total_comments = 0
    failed_files = 0
    with mp.Pool(
        processes=args.workers,
        initializer=worker_init,
    ) as pool:
        for result in pool.imap_unordered(
            process_file,
            (str(path) for path in files),
            chunksize=1,
        ):
            total_files += 1
            if result.error is not None:
                failed_files += 1
                print(
                    f"{result.path}: ERROR: {result.error}",
                    file=sys.stderr,
                )
                continue
            if result.changed:
                changed_files += 1
            total_comments += result.comments_removed
            print(
                f"{result.path}: {result.comments_removed} comment{'s' if result.comments_removed != 1 else ''} removed"
            )
    print()
    print(f"Files processed: {total_files}")
    print(f"Files changed:   {changed_files}")
    print(f"Total comments removed: {total_comments}")
    if failed_files:
        print(f"Files failed:    {failed_files}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
