i wanna add:
1. -t/--type presets (like ripgrep)
-e py is generic, but -t py could imply a curated set (.py, .pyi, .pyx) and honor --hidden, size limits, etc. More importantly it opens the door to non-code presets: -t md, -t json, -t log.
```bash
python pyrg.py -t py "def main"
python pyrg.py -t md "TODO"
```
Implementation: a TYPE_PRESETS: dict[str, set[str]] and merge into the extensions set.
2. -A/-B/-C context lines (after/before/around)
Very common need. -C 2 prints 2 lines of context around each match, using -- separators between non-contiguous groups like grep/rg.
```bash
python pyrg.py -e py -C 2 "raise ValueError"
```
Requires buffering nearby lines in search_file_text_mode — the only per-file change needed.
3. -v/--invert-match
Print lines that don't match. Trivial to add: flip the if spans: condition.
4. --stats
Print a summary at the end (to stderr):
```
3 files searched, 2 matched, 5 matches, 0.04s
```
A single counter accumulated in main — very useful when a search returns nothing and you want to know whether files were even scanned.
5. --no-messages and per-file error reporting
Right now unreadable files are silently swallowed (except Exception: pass). Add --no-messages to keep that silent, and by default print path: Permission denied to stderr.
6. --max-count N (-M)
Stop after N matches per file (like grep -m). Early-break in the line loop.
7. -q/--quiet
Suppress all output, just set exit code. Useful in scripts:
```bash
if python pyrg.py -q -e py "TODO"; then echo "found TODOs"; fi
```
8. --json output
Machine-readable results — one JSON object per match:
```json
{"path":"src/a.py","line":12,"col":5,"text":"def main():"}
```
Pipes cleanly into jq, editors, or your own tooling. Disables color automatically.
9. .gitignore / .ignore awareness
The biggest behavioral gap vs. rg. Currently IGNORED_DIRS is a hardcoded set. Honor .gitignore, .ignore, and --no-ignore to disable. Libraries like pathspec handle this well, but it's pure-Python implementable for the common cases.
10. --files mode (list files without searching)
List all files that would be searched, honoring all filters. Very useful for piping:
```bash
python pyrg.py -e py --files | xargs wc -l
```
Basically call get_files(...) and print each result; skip the pool entirely.
11. Regex capture groups in output
When the pattern has groups, print just the captured text (like rg -o --replace '$1'). Add -o/--only-matching (careful: -o is taken by --output — suggest --only-matching long-only, or rename output to --out).
Actually, given the conflict, I'd suggest renaming -o/--output to --save or --out-file and using -o/--only-matching for the ripgrep-compatible meaning. Worth deciding now before more scripts depend on it.
12. --replace REPL
Substitute matches with a replacement string in output (not in-place — that's a separate, scarier feature). Supports backreferences:
```bash
python pyrg.py -e py --replace 'logger.info($1)' 'print\((.*)\)'
```
13. --multiline
Allow patterns to span multiple lines. Today each line is matched independently. Requires reading the whole file and using regex.finditer on the full text — different result model.
14. Encoding detection / --encoding
Currently hardcoded utf-8 with errors="replace". Add --encoding latin-1 or use charset-normalizer for auto-detection. Relevant if you ever search logs from non-UTF-8 sources.
15. Symlink policy
Currently symlinks are always skipped. Add -L/--follow to follow them, with cycle detection (track visited (st_dev, st_ino) pairs).
16. --sort (path or none)
Currently results arrive in pool-completion order (nondeterministic). Sorting by path makes output reproducible — important for diffing or snapshot tests.
17. --heading / --no-heading (ripgrep-style grouping)
Instead of path:line:text on every line, print:
```
src/a.py
  12: def main():
  14:     return 0
src/b.py
   3: def main_helper():
```
More readable for human consumption.
18. --max-depth N
Limit directory recursion depth. walk_files likely supports it or can be wrapped.
19. --exclude-dir DIRNAME
Faster than -x "*/node_modules/*" for common cases. Just a name-based filter.
20. Progress indicator on stderr
For long searches: [####----] 1234/5678 files. Only when stderr is a TTY. Cheap and feels responsive.
21. Config file (~/.config/pyrg/config.toml)
Persist defaults: workers, hidden, extensions, ignored_dirs. Read at startup, overridden by CLI.
22. Colored filenames per-directory
Instead of one cyan for all paths, hash the directory to pick from a palette — makes multi-file output visually scannable.
23. Replace multiprocessing.Pool with concurrent.futures.ProcessPoolExecutor
Same performance, better API, as_completed lets you stream results as they arrive rather than in submission order. Strongly recommend this — your current code waits on async_result.get() in submission order, so a slow first file stalls everything behind it.
```python
with ProcessPoolExecutor(max_workers=args.workers) as ex:
    futures = {ex.submit(worker, arg): arg for arg in worker_args}
    for fut in as_completed(futures):
        path_str, matches = fut.result()
        ...
```
24. Avoid sending Path objects across process boundary
Currently worker receives a Path — picklable, but on some platforms paths get re-created with odd semantics. Sending str(path) and reconstructing inside the worker is more portable.
25. Handle re.error inside worker
If a pattern is somehow invalid in the worker (shouldn't happen — validated in main), the exception propagates as an opaque apply_async failure. Wrap in try/except and return a sentinel.
26. Distinguish "no matches" from "no files searched"
Currently both return exit code 1. Consider exit code 2 for "no files matched the filters" (grep uses 2 for errors; rg uses 1 for both). At least print a warning to stderr when candidates is empty.
27. --files-without-matches (-L in grep) Complementary to -l.
import argparse
import fnmatch
import operator
import re
import sys
from collections.abc import Generator
from multiprocessing import Pool
from pathlib import Path
from typing import TextIO
from dh import is_binary
from loguru import logger
from fastwalk import walk_files
logger.remove()
logger.add("/data/data/com.termux/files/home/tmp/apps/pyrg.log")
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
DEFAULT_WORKERS = 8
ANSI_BOLD = "\x1b[1m"
ANSI_RESET = "\x1b[0m"
ANSI_BLUE = "\x1b[94m"
ANSI_CYAN = "\x1b[5;96m"
TEXT_CHARS = bytes(range(32, 127)) + b"\n\r\t\x08"
def normalize_extension(value: str) -> str:
    v = value.strip().lower().rstrip(".")
    if not v:
        return ""
    if not v.startswith("."):
        v = "." + v
    return v
def parse_extension_args(raw_exts: list[str] | None) -> set[str]:
    result: set[str] = set()
    if not raw_exts:
        return result
    for raw in raw_exts:
        for piece in raw.split(","):
            ext = normalize_extension(piece)
            if ext:
                result.add(ext)
    return result
def get_files(
    paths: list[str],
    include_globs: list[str],
    exclude_globs: list[str],
    search_hidden: bool,
    max_size: int,
    extensions: set[str] | None = None,
) -> Generator[Path, None, None]:
    exts = extensions or set()
    def _passes_filters(p: Path) -> bool:
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
        if path.is_file() and not path.is_symlink():
            if _passes_filters(path):
                yield path
            continue
        if not path.is_dir() or path.is_symlink():
            continue
        for filepath in walk_files(path):
            if filepath.is_symlink():
                continue
            if _passes_filters(filepath):
                yield filepath
def colorize_line(line: str, spans: list[tuple[int, int]]) -> str:
    chars = list(line)
    for s, e in sorted(spans, key=operator.itemgetter(0), reverse=True):
        chars.insert(e, ANSI_RESET)
        chars.insert(s, ANSI_BLUE + ANSI_BOLD)
    return "".join(chars)
def matches_any_glob(path: Path, patterns: list[str]) -> bool:
    basename = path.name
    path_str = str(path)
    return any(
        fnmatch.fnmatch(path_str, p) or fnmatch.fnmatch(basename, p)
        for p in patterns
    )
def search_file_text_mode(
    path: Path,
    cwd: Path,
    regex: re.Pattern | None,
    fixed: str,
    ignore_case: bool,
) -> tuple[str, list[tuple[int, str, list[tuple[int, int]]]]]:
    matches: list[tuple[int, str, list[tuple[int, int]]]] = []
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for lineno, raw_line in enumerate(fh, start=1):
                line = raw_line.rstrip("\n\r")
                spans: list[tuple[int, int]] = []
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
def worker(args_tuple):
    path, cwd, regex_pattern, fixed, ignore_case = args_tuple
    compiled_regex = None
    if regex_pattern:
        flags = re.MULTILINE
        if ignore_case:
            flags |= re.IGNORECASE
        compiled_regex = re.compile(regex_pattern, flags)
    if is_binary(path):
        return (str(path), [])
    return search_file_text_mode(
        path=path,
        cwd=cwd,
        regex=compiled_regex,
        fixed=fixed,
        ignore_case=ignore_case,
    )
def open_output_sink(output_path: str | None) -> tuple[TextIO, bool]:
    if not output_path:
        return sys.stdout, False
    fh = open(output_path, "w", encoding="utf-8", newline="")
    return fh, True
def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="ripgrep-like recursive search in Python"
    )
    p.add_argument(
        "pattern", nargs="?",
        help="Regex pattern (positional) or use -r/--regexp",
    )
    p.add_argument(
        "-r", "--regexp", dest="pattern_e",
        help="Pattern (alternative to the positional argument)",
    )
    p.add_argument(
        "-i", "--ignore-case", action="store_true",
        help="Case-insensitive search",
    )
    p.add_argument(
        "-F", "--fixed-strings", action="store_true",
        help="Fixed string search (no regex)",
    )
    p.add_argument(
        "-n", "--line-number", action="store_true", default=True,
        help="Show line numbers",
    )
    p.add_argument(
        "-l", "--files-with-matches", action="store_true",
        help="Only print filenames that match",
    )
    p.add_argument(
        "-c", "--count", action="store_true",
        help="Print count of matches per file",
    )
    p.add_argument(
        "-w", "--workers", type=int, default=DEFAULT_WORKERS,
        help="Number of worker processes",
    )
    p.add_argument(
        "--hidden", action="store_true",
        help="Search hidden files and directories",
    )
    p.add_argument(
        "-g", "--glob", action="append",
        help="Include glob; can be repeated",
    )
    p.add_argument(
        "-x", "--exclude", action="append",
        help="Exclude glob; can be repeated",
    )
    p.add_argument(
        "-C", "--no-color", action="store_true",
        help="Disable colorized output",
    )
    p.add_argument(
        "-m", "--max-filesize", type=int, default=10_000_000,
        help="Skip files larger than size (bytes)",
    )
    p.add_argument(
        "-e", "--extension", dest="extensions", action="append", metavar="EXT",
        help=(
            "Only search files with the given extension(s). Accepts values "
            "with or without a leading dot, and comma-separated lists. "
            "Can be repeated. E.g. '-e py' or '-e py,pyi,pyx'."
        ),
    )
    p.add_argument(
        "-o", "--output", dest="output", metavar="FILE", default=None,
        help=(
            "Write matches to FILE instead of stdout. When set, ANSI color "
            "is disabled automatically unless stdout is a TTY and no file "
            "is given."
        ),
    )
    p.add_argument(
        "paths", nargs="*", default=["."],
        help="Files or directories to search (default: .)",
    )
    return p
def main(argv: list[str] | None = None) -> int:
    cwd = Path.cwd()
    args = build_argparser().parse_args(argv)
    pattern = args.pattern_e or args.pattern
    if not pattern:
        print(
            "No pattern provided. Use positional PATTERN or -r/--regexp PATTERN.",
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
    extensions = parse_extension_args(args.extensions)
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
    to_file = bool(args.output)
    color = (not args.no_color) and (not to_file) and sys.stdout.isatty()
    out_fh, should_close = open_output_sink(args.output)
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
    any_match = False
    try:
        with Pool(processes=args.workers) as pool:
            async_results = [pool.apply_async(worker, (arg,)) for arg in worker_args]
            try:
                for async_result in async_results:
                    path_str, matches = async_result.get()
                    if not matches:
                        continue
                    any_match = True
                    if args.files_with_matches:
                        print(path_str, file=out_fh)
                    elif args.count:
                        print(f"{path_str}:{len(matches)}", file=out_fh)
                    else:
                        for lineno, line, spans in matches:
                            out_line = colorize_line(line, spans) if color else line
                            if args.line_number:
                                print(
                                    f"{ANSI_CYAN}{path_str}{ANSI_RESET}:"
                                    f"{lineno}:{out_line}",
                                    file=out_fh,
                                )
                            else:
                                print(
                                    f"{ANSI_CYAN}{path_str}{ANSI_RESET}:{out_line}",
                                    file=out_fh,
                                )
            except KeyboardInterrupt:
                print("\nSearch cancelled.", file=sys.stderr)
                pool.terminate()
                pool.join()
                return 130
    finally:
        if should_close:
            out_fh.close()
            print(f"Results written to: {args.output}", file=sys.stderr)
    return 0 if any_match else 1
if __name__ == "__main__":
    raise SystemExit(main())
