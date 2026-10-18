#!/data/data/com.termux/files/usr/bin/python
"""Strip Python comments/docstrings recursively, updating files atomically.
Requires Python 3.14 for cf.interpreter; other backends work on 3.11+.
Install: python -m pip install tree-sitter tree-sitter-python
Optional: python -m pip install joblib
"""

from __future__ import annotations
import argparse
import ast
import codecs
import concurrent.futures as cf
import io
import multiprocessing as mp
import os
import re
import stat
import sys
import tempfile
import tokenize
from dataclasses import dataclass
from multiprocessing.pool import ThreadPool
from pathlib import Path
from typing import Iterable
import tree_sitter
import tree_sitter_python

_Edit = tuple[int, int, bytes]


@dataclass
class StripFileResult:
    path: Path
    saved: int = 0
    modified: bool = False
    error: str | None = None


class TSStripper:
    """Tree-sitter locates comments; AST identifies actual docstrings."""

    # Extend this list for project-specific tools. Deliberately conservative:
    # comments resembling tool instructions are retained rather than removed.
    _DIRECTIVE_RE = re.compile(
        r"^#\s*(?:type|fmt|mypy|pylint|ruff|pyright|basedpyright|noqa|"
        r"nosec|bandit|isort|yapf|autopep8|flake8|black|pyre|pytype|"
        r"pragma|coverage|doctest|pytest|cython|distutils|numba|"
        r"region|endregion|%%|</?editor-fold|\s*uv:)\b",
        re.I,
    )
    _COOKIE_RE = re.compile(rb"coding[:=]\s*[-\w.]+")

    def __init__(self, strip_comments: bool, strip_docstrings: bool):
        self.strip_comments = strip_comments
        self.strip_docstrings = strip_docstrings
        language = tree_sitter.Language(tree_sitter_python.language())
        self._parser = tree_sitter.Parser(language)

    @staticmethod
    def _line_start(src: bytes, pos: int) -> int:
        return src.rfind(b"\n", 0, pos) + 1

    @staticmethod
    def _line_end(src: bytes, pos: int) -> int:
        end = src.find(b"\n", pos)
        return len(src) if end < 0 else end + 1

    def _collect_comments(self, src: bytes) -> list[_Edit]:
        edits = []
        stack = [self._parser.parse(src).root_node]
        while stack:
            node = stack.pop()
            if node.type != "comment":
                stack.extend(reversed(node.children))
                continue
            text = src[node.start_byte : node.end_byte]
            row = node.start_point.row
            if (
                (row == 0 and text.startswith(b"#!"))
                or (row < 2 and self._COOKIE_RE.search(text))
                or self._DIRECTIVE_RE.match(text.decode("utf-8"))
            ):
                continue
            start = self._line_start(src, node.start_byte)
            if not src[start : node.start_byte].strip(b" \t"):
                edits.append((start, self._line_end(src, node.end_byte), b""))
            else:
                start = node.start_byte
                while start and src[start - 1 : start] in (b" ", b"\t"):
                    start -= 1
                # Leave newline characters untouched, including CRLF.
                edits.append((start, node.end_byte, b""))
        return edits

    def _collect_docstrings(self, src: bytes, tree: ast.AST) -> list[_Edit]:
        lines = src.splitlines(keepends=True)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))
        edits = []
        for node in ast.walk(tree):
            # Deliberately exclude Module: its docstring is always preserved.
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            first = node.body[0]
            if not (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                continue
            start = offsets[first.lineno - 1] + first.col_offset
            end = offsets[first.end_lineno - 1] + first.end_col_offset
            line_start = self._line_start(src, start)
            line_end = self._line_end(src, end)
            alone_on_lines = not src[line_start:start].strip() and not src[end:line_end].strip()
            if len(node.body) > 1 and alone_on_lines:
                edits.append((line_start, line_end, b""))
            else:
                # Keeps empty suites and one-line/semicolon suites valid.
                edits.append((start, end, b"pass"))
        return edits

    def strip(self, source: str) -> str:
        tree = ast.parse(source)  # Never rewrite invalid input.
        src = source.encode("utf-8")
        # Process docstrings first, then reparse for comment offsets. This avoids
        # overlapping edits when a deleted docstring line has a trailing comment.
        if self.strip_docstrings:
            src = self._apply(src, self._collect_docstrings(src, tree))
        if self.strip_comments:
            src = self._apply(src, self._collect_comments(src))
        result = src.decode("utf-8")
        ast.parse(result)  # Validate before writing.
        return result

    @staticmethod
    def _apply(src: bytes, edits: list[_Edit]) -> bytes:
        out = bytearray()
        cursor = 0
        for start, end, replacement in sorted(edits):
            if start < cursor:
                raise ValueError("Overlapping source edits")
            out.extend(src[cursor:start])
            out.extend(replacement)
            cursor = end
        out.extend(src[cursor:])
        return bytes(out)

    @staticmethod
    def _atomic_write(path: Path, data: bytes, original: bytes) -> None:
        mode = stat.S_IMODE(path.stat().st_mode)
        fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        temp = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            temp.chmod(mode)
            if path.is_symlink() or path.read_bytes() != original:
                raise RuntimeError("File changed while processing; not replaced")
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)

    def strip_file(self, path: Path) -> StripFileResult:
        try:
            if path.is_symlink():
                raise ValueError("Refusing to replace a symbolic link")
            original = path.read_bytes()
            encoding, _ = tokenize.detect_encoding(io.BytesIO(original).readline)
            source = original.decode(encoding)
            stripped = self.strip(source)
            # Round-tripping unchanged text needlessly can alter exotic encodings.
            if stripped == source:
                return StripFileResult(path)
            data = stripped.encode(encoding)
            if len(data) > len(original):
                return StripFileResult(path, error="Rewrite would increase size; left unchanged")
            self._atomic_write(path, data, original)
            return StripFileResult(path, len(original) - len(data), True)
        except Exception as exc:
            return StripFileResult(path, error=f"{type(exc).__name__}: {exc}")


def process_file(task: tuple[Path, bool, bool]) -> StripFileResult:
    path, comments, docstrings = task
    # Construct locally: tree-sitter parsers are not shared or pickled.
    try:
        return TSStripper(comments, docstrings).strip_file(path)
    except Exception as exc:
        return StripFileResult(path, error=f"{type(exc).__name__}: {exc}")


METHODS = (
    "mp.map",
    "mp.imap",
    "mp.imap_unordered",
    "mp.map_async",
    "mp.starmap",
    "mp.starmap_async",
    "mp.apply",
    "mp.apply_async",
    "threadpool.map",
    "threadpool.imap",
    "threadpool.imap_unordered",
    "threadpool.map_async",
    "threadpool.starmap",
    "threadpool.starmap_async",
    "threadpool.apply",
    "threadpool.apply_async",
    "cf.process",
    "cf.thread",
    "cf.interpreter",
    "joblib",
)


def run_tasks(tasks: list[tuple[Path, bool, bool]], method: str, workers: int) -> Iterable[StripFileResult]:
    if method.startswith(("mp.", "threadpool.")):
        pool_type = mp.Pool if method.startswith("mp.") else ThreadPool
        operation = method.split(".", 1)[1]
        with pool_type(workers) as pool:
            if operation == "apply":
                # apply blocks; this option is necessarily serial.
                for task in tasks:
                    yield pool.apply(process_file, (task,))
            elif operation == "apply_async":
                pending = [pool.apply_async(process_file, (task,)) for task in tasks]
                for result in pending:
                    yield result.get()
            elif operation in ("starmap", "starmap_async"):
                result = getattr(pool, operation)(process_file, [(task,) for task in tasks])
                yield from result.get() if operation.endswith("_async") else result
            elif operation == "map_async":
                yield from pool.map_async(process_file, tasks).get()
            else:
                yield from getattr(pool, operation)(process_file, tasks)
    elif method.startswith("cf."):
        name = {
            "cf.process": "ProcessPoolExecutor",
            "cf.thread": "ThreadPoolExecutor",
            "cf.interpreter": "InterpreterPoolExecutor",
        }[method]
        executor_type = getattr(cf, name, None)
        if executor_type is None:
            raise RuntimeError(f"{name} requires Python 3.14+")
        with executor_type(max_workers=workers) as executor:
            yield from executor.map(process_file, tasks)
    else:
        try:
            from joblib import Parallel, delayed
        except ImportError as exc:
            raise RuntimeError("Install joblib: python -m pip install joblib") from exc
        yield from Parallel(n_jobs=workers, backend="loky", return_as="generator")(
            delayed(process_file)(task) for task in tasks
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-c", action="store_true", help="Strip comments; preserve docstrings and tool directives")
    parser.add_argument("-d", action="store_true", help="Strip function/class docstrings; preserve module docstrings")
    parser.add_argument("--pool-method", choices=METHODS, default="mp.map", help="Execution backend (default: mp.map)")
    parser.add_argument("-j", "--workers", type=int, default=4, help="Worker count (default: 4)")
    parser.add_argument(
        "--color", choices=("auto", "always", "never"), default="auto", help="Color byte counts (default: auto)"
    )
    args = parser.parse_args()
    if not (args.c or args.d):
        parser.error("select -c, -d, or both")
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if args.pool_method == "cf.interpreter" and not hasattr(cf, "InterpreterPoolExecutor"):
        parser.error("cf.interpreter requires Python 3.14+")
    if args.pool_method == "joblib":
        import importlib.util

        if importlib.util.find_spec("joblib") is None:
            parser.error("install joblib: python -m pip install joblib")
    # pathlib does not follow directory symlinks by default. Skip file symlinks too.
    paths = sorted(p for p in Path.cwd().rglob("*.py") if p.is_file() and not p.is_symlink())
    tasks = [(p, args.c, args.d) for p in paths]
    color = args.color == "always" or (args.color == "auto" and sys.stdout.isatty() and "NO_COLOR" not in os.environ)

    def green(number: int) -> str:
        text = f"{number:,}"
        return f"\033[32m{text}\033[0m" if color else text

    width = max((len(p.name) for p in paths), default=0)
    total = errors = 0
    try:
        for result in run_tasks(tasks, args.pool_method, args.workers):
            if result.error:
                errors += 1
                print(f"{result.path.name}: {result.error}", file=sys.stderr, flush=True)
            else:
                total += result.saved
                print(f"{result.path.name:<{width}}  {green(result.saved)}", flush=True)
    except Exception as exc:
        print(f"Backend error: {exc}", file=sys.stderr)
        errors += 1
    print(f"\nTotal space freed: {green(total)} bytes")
    return 1 if errors else 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
