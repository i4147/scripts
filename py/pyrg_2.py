"""A small ripgrep-like recursive file searcher written in pure Python.

Flags:
  * ``-r/--regexp PATTERN``   — explicit pattern (alternative to positional)
  * ``-e/--extension EXT``    — restrict to given extension(s); repeatable
"""

from __future__ import annotations

import argparse
import fnmatch
import operator
import re
import sys
from collections.abc import Generator
from multiprocessing import Pool
from pathlib import Path

from dh import is_binary  # helper that detects binary files
from loguru import logger  # logging
from fastwalk import walk_files  # fast recursive directory walker

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
logger.remove()  # drop default stderr sink
logger.add("/data/data/com.termux/files/home/tmp/apps/pyrg.log")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
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
BINARY_CHUNK = 8192  # (retained for compatibility)
DEFAULT_WORKERS = 8  # default process-pool size
ANSI_BOLD = "\x1b[1m"
ANSI_RESET = "\x1b[0m"
ANSI_BLUE = "\x1b[94m"
ANSI_CYAN = "\x1b[5;96m"
TEXT_CHARS = bytes(range(32, 127)) + b"\n\r\t\x08"  # (retained for compatibility)


# ---------------------------------------------------------------------------
# Extension helpers
# ---------------------------------------------------------------------------
def normalize_extension(value: str) -> str:
    """Return an extension normalized to a lower-cased string with a leading dot.

    ``"py"``, ``".py"``, ``"PY"`` and ``".PY"`` all become ``".py"``.
    A single trailing dot is stripped (e.g. ``"py."`` -> ``".py"``).
    """
    v = value.strip().lower().rstrip(".")
    if not v:
        return ""
    if not v.startswith("."):
        v = "." + v
    return v


def parse_extension_args(raw_exts: list[str] | None) -> set[str]:
    """Flatten repeated ``-e`` values and comma-separated lists into a set.

    ``["py,pyi", ".js"]`` -> ``{".py", ".pyi", ".js"}``
    """
    result: set[str] = set()
    if not raw_exts:
        return result
    for raw in raw_exts:
        for piece in raw.split(","):
            ext = normalize_extension(piece)
            if ext:
                result.add(ext)
    return result


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------
def get_files(
    paths: list[str],
    include_globs: list[str],
    exclude_globs: list[str],
    search_hidden: bool,
    max_size: int,
    extensions: set[str] | None = None,
) -> Generator[Path, None, None]:
    """Yield candidate files to search.

    Parameters
    ----------
    paths
        Files or directories supplied on the command line.
    include_globs
        If non-empty, only paths matching one of these globs are yielded.
    exclude_globs
        Paths matching any of these globs are skipped.
    search_hidden
        When False, skip files/dirs whose name starts with a dot.
    max_size
        Skip files larger than this many bytes (0 disables the check).
    extensions
        If non-empty, only files whose (lower-cased) suffix is in this set
        are yielded. Each entry must already be normalized (see
        :func:`normalize_extension`).
    """
    exts = extensions or set()

    def _passes_filters(p: Path) -> bool:
        """Shared filter logic for both explicit files and walked files."""
        # Extension filter (case-insensitive on the suffix).
        if exts and p.suffix.lower() not in exts:
            return False
        if not search_hidden and p.name.startswith("."):
            return False
        if max_size:
            try:
                if p.stat().st_size > max_size:
                    return False
            except OSError:
                return False
        if include_globs and not matches_any_glob(p, include_globs):
            return False
        if exclude_globs and matches_any_glob(p, exclude_globs):
            return False
        return True

    for p_str in paths:
        path = Path(p_str)

        # --- Explicit file argument -------------------------------------
        if path.is_file() and not path.is_symlink():
            if _passes_filters(path):
                yield path
            continue

        # --- Directory (or invalid path) --------------------------------
        if not path.is_dir() or path.is_symlink():
            continue

        for filepath in walk_files(path):
            if filepath.is_symlink():
                continue
            if _passes_filters(filepath):
                yield filepath


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------
def colorize_line(line: str, spans: list[tuple[int, int]]) -> str:
    """Wrap each match span in `line` with ANSI bold+blue codes."""
    chars = list(line)
    # Insert from the end so earlier indices remain valid.
    for s, e in sorted(spans, key=operator.itemgetter(0), reverse=True):
        chars.insert(e, ANSI_RESET)
        chars.insert(s, ANSI_BLUE + ANSI_BOLD)
    return "".join(chars)


def matches_any_glob(path: Path, patterns: list[str]) -> bool:
    """True if `path` matches any of the fnmatch patterns (full path or name)."""
    basename = path.name
    path_str = str(path)
    return any(fnmatch.fnmatch(path_str, p) or fnmatch.fnmatch(basename, p) for p in patterns)


# ---------------------------------------------------------------------------
# Per-file search
# ---------------------------------------------------------------------------
def search_file_text_mode(
    path: Path,
    cwd: Path,
    regex: re.Pattern | None,
    fixed: str,
    ignore_case: bool,
) -> tuple[str, list[tuple[int, str, list[tuple[int, int]]]]]:
    """Search a single file in text mode.

    Returns a tuple of ``(relative_path, matches)`` where each match is
    ``(line_number, line_text, [(start, end), ...])``.
    """
    matches: list[tuple[int, str, list[tuple[int, int]]]] = []

    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for lineno, raw_line in enumerate(fh, start=1):
                line = raw_line.rstrip("\n\r")
                spans: list[tuple[int, int]] = []

                if regex:
                    # Regex mode.
                    spans = [(m.start(), m.end()) for m in regex.finditer(line)]
                else:
                    # Fixed-string mode (optionally case-insensitive).
                    hay = line.lower() if ignore_case else line
                    needle = fixed.lower() if ignore_case else fixed
                    start = 0
                    while (idx := hay.find(needle, start)) != -1:
                        spans.append((idx, idx + len(needle)))
                        # Advance by at least 1 to avoid infinite loop on empty needle.
                        start = idx + max(1, len(needle))

                if spans:
                    matches.append((lineno, line, spans))
    except Exception:
        # Unreadable files are silently skipped.
        pass

    # Present the path relative to the CWD when possible.
    try:
        rel_path = str(path.relative_to(cwd))
    except ValueError:
        rel_path = str(path)

    return (rel_path, matches)


def worker(args_tuple):
    """Process-pool entry point: search one file."""
    path, cwd, regex_pattern, fixed, ignore_case = args_tuple

    # Compile the regex inside the worker (cheap; processes are isolated).
    compiled_regex = None
    if regex_pattern:
        flags = re.MULTILINE
        if ignore_case:
            flags |= re.IGNORECASE
        compiled_regex = re.compile(regex_pattern, flags)

    # Skip binaries early.
    if is_binary(path):
        return (str(path), [])

    return search_file_text_mode(
        path=path,
        cwd=cwd,
        regex=compiled_regex,
        fixed=fixed,
        ignore_case=ignore_case,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="ripgrep-like recursive search in Python")
    p.add_argument(
        "pattern",
        nargs="?",
        help="Regex pattern (positional) or use -r/--regexp",
    )
    # CHANGED: --regexp now has short form -r (was -e).
    p.add_argument(
        "-r",
        "--regexp",
        dest="pattern_e",
        help="Pattern (alternative to the positional argument)",
    )
    p.add_argument(
        "-i",
        "--ignore-case",
        action="store_true",
        help="Case-insensitive search",
    )
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
    p.add_argument(
        "-c",
        "--count",
        action="store_true",
        help="Print count of matches per file",
    )
    p.add_argument(
        "-w",
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="Number of worker processes",
    )
    p.add_argument(
        "--hidden",
        action="store_true",
        help="Search hidden files and directories",
    )
    p.add_argument(
        "-g",
        "--glob",
        action="append",
        help="Include glob; can be repeated",
    )
    p.add_argument(
        "-x",
        "--exclude",
        action="append",
        help="Exclude glob; can be repeated",
    )
    p.add_argument(
        "-C",
        "--no-color",
        action="store_true",
        help="Disable colorized output",
    )
    p.add_argument(
        "-m",
        "--max-filesize",
        type=int,
        default=10_000_000,
        help="Skip files larger than size (bytes)",
    )
    # -e now exclusively means --extension.
    p.add_argument(
        "-e",
        "--extension",
        dest="extensions",
        action="append",
        metavar="EXT",
        help=(
            "Only search files with the given extension(s). Accepts values "
            "with or without a leading dot, and comma-separated lists. "
            "Can be repeated. E.g. '-e py' or '-e py,pyi,pyx'."
        ),
    )
    p.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to search (default: .)",
    )
    return p


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    cwd = Path.cwd()
    args = build_argparser().parse_args(argv)

    # --- Resolve pattern ---------------------------------------------------
    pattern = args.pattern_e or args.pattern
    if not pattern:
        print(
            "No pattern provided. Use positional PATTERN or -r/--regexp PATTERN.",
            file=sys.stderr,
        )
        return 2

    # --- Compile regex (unless -F) -----------------------------------------
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

    # --- Parse extensions --------------------------------------------------
    extensions = parse_extension_args(args.extensions)

    # --- Collect candidate files ------------------------------------------
    candidates = list(
        get_files(
            paths=args.paths,
            include_globs=args.glob or [],
            exclude_globs=args.exclude or [],
            search_hidden=args.hidden,
            max_size=args.max_filesize,
            extensions=extensions,
        )
    )

    color = not args.no_color and sys.stdout.isatty()
    any_match = False

    # --- Build worker payloads --------------------------------------------
    worker_args = [
        (
            path,
            cwd,
            pattern if not args.fixed_strings else None,
            pattern if args.fixed_strings else "",
            args.ignore_case,
        )
        for path in candidates
    ]

    # --- Search in parallel and stream results ----------------------------
    with Pool(processes=args.workers) as pool:
        async_results = [pool.apply_async(worker, (arg,)) for arg in worker_args]
        try:
            for async_result in async_results:
                path_str, matches = async_result.get()
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
            pool.terminate()
            pool.join()
            return 130

    # Exit code mirrors ripgrep: 0 = found, 1 = nothing found.
    return 0 if any_match else 1


if __name__ == "__main__":
    raise SystemExit(main())
