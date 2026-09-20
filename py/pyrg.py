from __future__ import annotations

import argparse
import fnmatch
import operator
import re
import sys
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from loguru import logger

logger.remove()
logger.add("/data/data/com.termux/files/home/tmp/log/apps/pyrg.log")
IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".ruff_cache",
    ".pytest_cache",
    ".mypy_cache",
}
BINARY_CHUNK = 8192
DEFAULT_THREADS = 4
ANSI_BOLD = "\x1b[1m"
ANSI_RESET = "\x1b[0m"
ANSI_BLUE = "\x1b[94m"
ANSI_CYAN = "\x1b[5;96m"
TEXT_CHARS = bytes(range(32, 127)) + b"\n\r\t\x08"


def get_files(
    paths: list[str],
    include_globs: list[str],
    exclude_globs: list[str],
    search_hidden: bool,
    max_size: int,
) -> Generator[Path, None, None]:
    for p_str in paths:
        path = Path(p_str)
        if path.is_file() and not path.is_symlink():
            if not search_hidden and path.name.startswith("."):
                continue
            if max_size and path.stat().st_size > max_size:
                continue
            if include_globs and not matches_any_glob(path, include_globs):
                continue
            if exclude_globs and matches_any_glob(path, exclude_globs):
                continue
            yield path
            continue
        if not path.is_dir() or path.is_symlink():
            continue
        for root, dirs, walk_files in path.walk(top_down=True, follow_symlinks=False):
            if not search_hidden:
                dirs[:] = [d for d in dirs if not d.startswith(".")]
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            for f in walk_files:
                if not search_hidden and f.startswith("."):
                    continue
                file_path = root / f
                if file_path.is_symlink():
                    continue
                try:
                    if max_size and file_path.stat().st_size > max_size:
                        continue
                except OSError:
                    continue
                if include_globs and not matches_any_glob(file_path, include_globs):
                    continue
                if exclude_globs and matches_any_glob(file_path, exclude_globs):
                    continue
                yield file_path


def is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            chunk = f.read(BINARY_CHUNK)
        if not chunk:
            return False
        if b"\x00" in chunk:
            return True
        non_text_len = len(chunk.translate(None, TEXT_CHARS))
        return non_text_len / len(chunk) > 0.3
    except Exception:
        return True


def colorize_line(line: str, spans: list[tuple[int, int]]) -> str:
    chars = list(line)
    for s, e in sorted(spans, key=operator.itemgetter(0), reverse=True):
        chars.insert(e, ANSI_RESET)
        chars.insert(s, ANSI_BLUE + ANSI_BOLD)
    return "".join(chars)


def matches_any_glob(path: Path, patterns: list[str]) -> bool:
    basename = path.name
    path_str = str(path)
    return any(fnmatch.fnmatch(path_str, p) or fnmatch.fnmatch(basename, p) for p in patterns)


def search_file_text_mode(
    path: Path, cwd: Path, regex: re.Pattern | None, fixed: str, ignore_case: bool
) -> tuple[str, list[tuple[int, str, list[tuple[int, int]]]]]:
    matches = []
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for lineno, raw_line in enumerate(fh, start=1):
                line = raw_line.rstrip("\n\r")
                spans = []
                if regex:
                    spans = [(m.start(), m.end()) for m in regex.finditer(line)]
                else:
                    hay = line.lower() if ignore_case else line
                    needle = fixed.lower() if ignore_case else fixed
                    start = 0
                    while (idx := hay.find(needle, start)) != -1:
                        spans.append((idx, idx + len(needle)))
                        start = idx + max(1, len(needle))
                if spans:
                    matches.append((lineno, line, spans))
    except Exception:
        pass
    try:
        rel_path = str(path.relative_to(cwd))
    except ValueError:
        rel_path = str(path)
    return (rel_path, matches)


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="ripgrep-like recursive search in Python")
    p.add_argument("pattern", nargs="?", help="Regex pattern (positional) or use -e")
    p.add_argument("-e", "--regexp", dest="pattern_e", help="Pattern (alternative to positional)")
    p.add_argument("-i", "--ignore-case", action="store_true", help="Case-insensitive search")
    p.add_argument(
        "-F",
        "--fixed-strings",
        action="store_true",
        help="Fixed string search (no regex)",
    )
    p.add_argument(
        "-n",
        "--line-number",
        action="store_true",
        default=True,
        help="Show line numbers",
    )
    p.add_argument(
        "-l",
        "--files-with-matches",
        action="store_true",
        help="Only print filenames that match",
    )
    p.add_argument("-c", "--count", action="store_true", help="Print count of matches per file")
    p.add_argument(
        "-t",
        "--threads",
        type=int,
        default=DEFAULT_THREADS,
        help="Number of worker threads",
    )
    p.add_argument("--hidden", action="store_true", help="Search hidden files and directories")
    p.add_argument("-g", "--glob", action="append", help="Include glob; can be repeated")
    p.add_argument("-x", "--exclude", action="append", help="Exclude glob; can be repeated")
    p.add_argument("-C", "--no-color", action="store_true", help="Disable colorized output")
    p.add_argument(
        "-m",
        "--max-filesize",
        type=int,
        default=10000000,
        help="Skip files larger than size (bytes)",
    )
    p.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to search (default: .)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    cwd = Path.cwd()
    args = build_argparser().parse_args(argv)
    pattern = args.pattern_e or args.pattern
    if not pattern:
        print(
            "No pattern provided. Use positional PATTERN or -e PATTERN.",
            file=sys.stderr,
        )
        return 2
    compiled = None
    if not args.fixed_strings:
        flags = re.MULTILINE
        if args.ignore_case:
            flags |= re.IGNORECASE
        try:
            compiled = re.compile(pattern, flags)
        except re.error as ex:
            print(f"Invalid regex: {ex}", file=sys.stderr)
            return 2
    candidates = get_files(
        paths=args.paths,
        include_globs=args.glob or [],
        exclude_globs=args.exclude or [],
        search_hidden=args.hidden,
        max_size=args.max_filesize,
    )
    color = not args.no_color and sys.stdout.isatty()
    any_match = False

    def worker(path: Path):
        if is_binary(path):
            return (str(path), [])
        return search_file_text_mode(
            path=path,
            cwd=cwd,
            regex=compiled,
            fixed=pattern,
            ignore_case=args.ignore_case,
        )

    with ThreadPoolExecutor(max_workers=args.threads) as executor:
        futures = {executor.submit(worker, p): p for p in candidates}
        try:
            for fut in as_completed(futures):
                path_str, matches = fut.result()
                if not matches:
                    continue
                any_match = True
                if args.files_with_matches:
                    print(path_str)
                elif args.count:
                    print(f"{path_str}:{len(matches)}")
                else:
                    for lineno, line, spans in matches:
                        out_line = colorize_line(line, spans) if color else line
                        if args.line_number:
                            print(f"{ANSI_CYAN}{path_str}{ANSI_RESET}:{lineno}:{out_line}")
                        else:
                            print(f"{ANSI_CYAN}{path_str}{ANSI_RESET}:{out_line}")
        except KeyboardInterrupt:
            print("\nSearch cancelled.", file=sys.stderr)
            return 130
    return 0 if any_match else 1


if __name__ == "__main__":
    raise SystemExit(main())
