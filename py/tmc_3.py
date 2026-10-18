#!/data/data/com.termux/files/usr/bin/python
"""Strip Python comments/docstrings recursively, updating files atomically.
AST backend: no third-party dependencies.
Requires Python 3.14 for cf.interpreter; other backends work on 3.11+.
Install: python -m pip install tree-sitter tree-sitter-python
LibCST backend: python -m pip install libcst
Optional: python -m pip install joblib
"""

from __future__ import annotations
import argparse
import ast
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
from typing import Iterator, TypeAlias

_Edit = tuple[int, int, bytes]


@dataclass
class StripFileResult:
    path: Path
    saved: int = 0
    modified: bool = False
    error: str | None = None


class ASTStripper:
    # Extend this list for project-specific tools. Deliberately conservative:
    # comments resembling tool instructions are retained rather than removed.
    _DIRECTIVE_RE = re.compile(
        r"^#\s*(?:type|fmt|mypy|pylint|ruff|pyright|basedpyright|noqa|"
        r"nosec|bandit|isort|yapf|autopep8|flake8|black|pyre|pytype|"
        r"pragma|coverage|doctest|pytest|cython|distutils|numba|"
        r"region|endregion|uv)\b|^#\s*(?:%%|</?editor-fold\b)",
        re.I,
    )
    _COOKIE_RE = re.compile(rb"coding[:=]\s*[-\w.]+")

    def __init__(self, strip_comments: bool, strip_docstrings: bool, remove_blank_lines: bool = False) -> None:
        self.strip_comments = strip_comments
        self.strip_docstrings = strip_docstrings
        self.remove_blank_lines = remove_blank_lines

    @staticmethod
    def _line_start(src: bytes, pos: int) -> int:
        return src.rfind(b"\n", 0, pos) + 1

    @staticmethod
    def _line_end(src: bytes, pos: int) -> int:
        end = src.find(b"\n", pos)
        return len(src) if end < 0 else end + 1

    @classmethod
    def _keep_comment(cls, text: str, row: int) -> bool:
        return bool(
            (row == 0 and text.startswith("#!"))
            or (row < 2 and cls._COOKIE_RE.search(text.encode("utf-8")))
            or cls._DIRECTIVE_RE.match(text)
        )

    def _collect_comments(self, src: bytes) -> list[_Edit]:
        source = src.decode("utf-8")
        lines = io.StringIO(source).readlines()
        offsets: list[int] = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line.encode("utf-8")))
        edits: list[_Edit] = []
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type != tokenize.COMMENT:
                continue
            row, column = token.start
            if self._keep_comment(token.string, row - 1):
                continue
            line = lines[row - 1]
            line_start = offsets[row - 1]
            start = line_start + len(line[:column].encode("utf-8"))
            end = line_start + len(line[: token.end[1]].encode("utf-8"))
            if not src[line_start:start].strip(b" \t"):
                edits.append((line_start, self._line_end(src, end), b""))
            else:
                while start > line_start and src[start - 1 : start] in (b" ", b"\t"):
                    start -= 1
                edits.append((start, end, b""))
        return edits

    def _collect_docstrings(self, src: bytes, tree: ast.AST) -> list[_Edit]:
        lines = src.splitlines(keepends=True)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))
        edits: list[_Edit] = []
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
            assert first.end_lineno is not None and first.end_col_offset is not None
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
        if self.remove_blank_lines:
            result = remove_blank_lines(result)
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


def remove_blank_lines(source: str) -> str:
    protected: set[int] = set()
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for token in tokens:
        if token.start[0] != token.end[0]:
            protected.update(range(token.start[0], token.end[0] + 1))
    lines = io.StringIO(source).readlines()
    for row, line in enumerate(lines, 1):
        if line.rstrip("\r\n").endswith("\\"):
            protected.add(row + 1)
        # Keep encoding declarations in their original physical header position.
        if row <= 2 and ASTStripper._COOKIE_RE.search(line.encode("utf-8")):
            protected.update(range(1, row + 1))
    result = "".join(line for row, line in enumerate(lines, 1) if row in protected or line.strip(" \t\f\r\n"))
    before = ast.dump(ast.parse(source), include_attributes=False)
    after = ast.dump(ast.parse(result), include_attributes=False)
    if before != after:
        raise ValueError("Blank-line removal would change the AST; not written")
    return result


class TSStripper(ASTStripper):
    def __init__(self, strip_comments: bool, strip_docstrings: bool, remove_blank_lines: bool = False) -> None:
        super().__init__(strip_comments, strip_docstrings, remove_blank_lines)
        import tree_sitter
        import tree_sitter_python

        self._parser = tree_sitter.Parser(tree_sitter.Language(tree_sitter_python.language()))

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


def _libcst_strip(source: str, comments: bool, docstrings: bool) -> str:
    # Lazy import: tree-sitter users do not need LibCST, and vice versa.
    import libcst as cst
    from libcst.metadata import MetadataWrapper, PositionProvider

    class _CommentRemover(cst.CSTTransformer):
        METADATA_DEPENDENCIES = (PositionProvider,)

        def _keep(self, comment: cst.Comment) -> bool:
            line = self.get_metadata(PositionProvider, comment).start.line
            text = comment.value
            return bool(
                (line == 1 and text.startswith("#!"))
                or (line <= 2 and ASTStripper._COOKIE_RE.search(text.encode("utf-8")))
                or ASTStripper._DIRECTIVE_RE.match(text)
            )

        def leave_EmptyLine(
            self, original_node: cst.EmptyLine, updated_node: cst.EmptyLine
        ) -> cst.EmptyLine | cst.RemovalSentinel:
            if original_node.comment is not None and not self._keep(original_node.comment):
                return cst.RemoveFromParent()
            return updated_node

        def leave_TrailingWhitespace(
            self, original_node: cst.TrailingWhitespace, updated_node: cst.TrailingWhitespace
        ) -> cst.TrailingWhitespace:
            if original_node.comment is not None and not self._keep(original_node.comment):
                return updated_node.with_changes(comment=None, whitespace=cst.SimpleWhitespace(""))
            return updated_node

    class _DocstringRemover(cst.CSTTransformer):
        @staticmethod
        def _is_docstring(expr: cst.CSTNode) -> bool:
            # SimpleString also includes bytes literals, which are NOT docstrings.
            # ConcatenatedString may contain formatted strings: exclude those too.
            if not isinstance(expr, cst.Expr):
                return False
            if not isinstance(expr.value, (cst.SimpleString, cst.ConcatenatedString)):
                return False
            try:
                value = ast.literal_eval(cst.Module([]).code_for_node(expr.value))
            except (ValueError, SyntaxError):
                return False
            return isinstance(value, str)

        def _strip_suite(self, suite: cst.BaseSuite) -> cst.BaseSuite:
            if isinstance(suite, cst.SimpleStatementSuite):
                if suite.body and self._is_docstring(suite.body[0]):
                    # Retain separators and any trailing comment verbatim.
                    first = suite.body[0]
                    return suite.with_changes(body=[cst.Pass(semicolon=first.semicolon), *suite.body[1:]])
                return suite
            if not isinstance(suite, cst.IndentedBlock) or not suite.body:
                return suite
            first = suite.body[0]
            if not isinstance(first, cst.SimpleStatementLine) or not first.body:
                return suite
            if not self._is_docstring(first.body[0]):
                return suite
            if len(first.body) == 1 and len(suite.body) > 1 and first.trailing_whitespace.comment is None:
                rest = list(suite.body[1:])
                next_stmt = rest[0]
                assert isinstance(next_stmt, (cst.SimpleStatementLine, cst.BaseCompoundStatement))
                rest[0] = next_stmt.with_changes(leading_lines=(*first.leading_lines, *next_stmt.leading_lines))
                return suite.with_changes(body=rest)
            replacement = first.with_changes(body=[cst.Pass(semicolon=first.body[0].semicolon), *first.body[1:]])
            return suite.with_changes(body=[replacement, *suite.body[1:]])

        def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
            # Includes async functions. Module and control-flow blocks are untouched.
            return updated_node.with_changes(body=self._strip_suite(updated_node.body))

        def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
            return updated_node.with_changes(body=self._strip_suite(updated_node.body))

    ast.parse(source)
    module = cst.parse_module(source)
    if docstrings:
        module = module.visit(_DocstringRemover())
    if comments:
        module = MetadataWrapper(module).visit(_CommentRemover())
    result = module.code
    ast.parse(result)
    return result


class CSTStripper(ASTStripper):
    def strip(self, source: str) -> str:
        result = _libcst_strip(source, self.strip_comments, self.strip_docstrings)
        return remove_blank_lines(result) if self.remove_blank_lines else result


Task: TypeAlias = tuple[Path, bool, bool, str, bool]


def process_file(task: Task) -> StripFileResult:
    path, comments, docstrings, backend, blank_lines = task
    # Construct locally: tree-sitter parsers are not shared or pickled.
    try:
        stripper_type = {"tree-sitter": TSStripper, "libcst": CSTStripper, "ast": ASTStripper}[backend]
        return stripper_type(comments, docstrings, blank_lines).strip_file(path)
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


def run_tasks(tasks: list[Task], method: str, workers: int) -> Iterator[StripFileResult]:
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
    parser.add_argument(
        "-b",
        "--backend",
        choices=("tree-sitter", "libcst", "ast"),
        default="tree-sitter",
        help="Stripping backend (default: tree-sitter)",
    )
    parser.add_argument(
        "--remove-blank-lines", action="store_true", help="Remove blank lines outside strings (usable alone)"
    )
    parser.add_argument("--pool-method", choices=METHODS, default="mp.map", help="Execution backend (default: mp.map)")
    parser.add_argument("-j", "--workers", type=int, default=4, help="Worker count (default: 4)")
    parser.add_argument(
        "--color", choices=("auto", "always", "never"), default="auto", help="Color byte counts (default: auto)"
    )
    args = parser.parse_args()
    if not (args.c or args.d or args.remove_blank_lines):
        parser.error("select -c, -d, and/or --remove-blank-lines")
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if args.pool_method == "cf.interpreter" and not hasattr(cf, "InterpreterPoolExecutor"):
        parser.error("cf.interpreter requires Python 3.14+")
    if args.pool_method == "joblib":
        import importlib.util

        if importlib.util.find_spec("joblib") is None:
            parser.error("install joblib: python -m pip install joblib")
    import importlib.util

    dependencies = (
        ("tree_sitter", "tree_sitter_python")
        if args.backend == "tree-sitter"
        else (("libcst",) if args.backend == "libcst" else ())
    )
    if any(importlib.util.find_spec(name) is None for name in dependencies):
        packages = "tree-sitter tree-sitter-python" if args.backend == "tree-sitter" else "libcst"
        parser.error(f"install selected backend: python -m pip install {packages}")
    # pathlib does not follow directory symlinks by default. Skip file symlinks too.
    paths = sorted(p for p in Path.cwd().rglob("*.py") if p.is_file() and not p.is_symlink())
    tasks: list[Task] = [(p, args.c, args.d, args.backend, args.remove_blank_lines) for p in paths]
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
