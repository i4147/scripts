#!/data/data/com.termux/files/usr/bin/env python

import argparse
import ast
import contextlib
import dataclasses
import io
import multiprocessing as mp
import os
import re
import signal
import sys
import tempfile
import textwrap
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, Sequence
import libcst as cst

PROGRAM = "strip_comments"
VERSION = "2.1.0"
DEFAULT_MAX_PROCESSES = 8
DEFAULT_CHUNK_SIZE = 8
PARALLEL_MIN_FILES = 4
PY_SUFFIXES = (".py", ".pyi", ".pyw")
BACKUP_SUFFIX = ".pystripbak"
GREEN = "\x1b[32m"
RESET = "\x1b[0m"
DEFAULT_SKIP_DIR_NAMES = frozenset({
    ".git",
    ".hg",
    ".svn",
    ".tox",
    ".nox",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "build",
    "dist",
    ".eggs",
})
PROTECTED_COMMENT_RE = re.compile(
    r"#(?:!|\s*(?:-\*-.*coding|coding[:=]|noqa\b|nosec\b|pragma\b|"
    r"(?:type|fmt|isort|mypy|pyright|pytype|pylint|ruff|flake8|yapf):))",
    re.IGNORECASE,
)
TYPE_COMMENT_RE = re.compile(r"#\s*type:\s*(?!ignore\b)", re.IGNORECASE)
CODING_RE = re.compile(r"[ \t\f]*#.*?coding[:=][ \t]*[-\w.]+")
BLANK_RUN_RE = re.compile(r"(?:\A|\n)[ \t\r]*\n[ \t\r]*\n")
_STRING_STARTS = frozenset(getattr(tokenize, n) for n in ("FSTRING_START", "TSTRING_START") if hasattr(tokenize, n))
_STRING_ENDS = frozenset(getattr(tokenize, n) for n in ("FSTRING_END", "TSTRING_END") if hasattr(tokenize, n))
_NO_LINES: frozenset[int] = frozenset()


@dataclass(frozen=True, slots=True)
class TransformOptions:
    remove_all: bool
    remove_all_comments: bool
    remove_docstrings: bool
    remove_module_docstring: bool
    remove_type_annotations: bool
    strip_class_annotations: bool
    remove_commented_code: bool
    collapse_blank_lines: bool
    make_backup: bool
    overwrite_backup: bool
    fsync: bool
    dry_run: bool


@dataclass(frozen=True, slots=True)
class FileResult:
    path: Path
    old_size: int = 0
    new_size: int = 0
    changed: bool = False
    error: str | None = None

    @property
    def bytes_reduced(self) -> int:
        return self.old_size - self.new_size


def _safe_cwd() -> str:
    try:
        return os.getcwd()
    except OSError:
        return "."


_CWD = _safe_cwd()


def format_size(num_bytes: int) -> str:
    sign = "-" if num_bytes < 0 else ""
    value = abs(num_bytes)
    if value < 1024:
        return f"{sign}{value} B"
    for suffix, threshold in (("G", 1024**3), ("M", 1024**2), ("k", 1024)):
        if value >= threshold:
            text = f"{value / threshold:.1f}".rstrip("0").rstrip(".")
            return f"{sign}{text}{suffix}"
    return f"{sign}{value} B"


def display_path(path: Path | str) -> str:
    try:
        return os.path.relpath(path, _CWD)
    except ValueError:
        return str(path)


def emit(*parts: str, file=None) -> None:
    try:
        print(*parts, file=file)
    except BrokenPipeError:
        with contextlib.suppress(Exception):
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())


def warn(message: str) -> None:
    emit(f"warning: {message}", file=sys.stderr)


def is_docstring_literal(expr: cst.BaseExpression) -> bool:
    if isinstance(expr, cst.SimpleString):
        return "b" not in expr.prefix.lower()
    if isinstance(expr, cst.ConcatenatedString):
        return is_docstring_literal(expr.left) and is_docstring_literal(expr.right)
    return False


def starts_with_docstring(line: cst.SimpleStatementLine) -> bool:
    if not line.body:
        return False
    first = line.body[0]
    return isinstance(first, cst.Expr) and is_docstring_literal(first.value)


def _with_leading(node: cst.CSTNode, extra: Sequence[cst.EmptyLine]) -> cst.CSTNode:
    existing = getattr(node, "leading_lines", None)
    if existing is None:
        return node
    return node.with_changes(leading_lines=[*extra, *existing])


def strip_indented_block_docstring(
    block: cst.IndentedBlock,
) -> tuple[cst.IndentedBlock, bool]:
    if not block.body:
        return block, False
    first = block.body[0]
    if not (isinstance(first, cst.SimpleStatementLine) and starts_with_docstring(first)):
        return block, False
    tail = list(first.body[1:])
    later = list(block.body[1:])
    if tail:
        return block.with_changes(body=[first.with_changes(body=tail), *later]), True
    if not later or first.trailing_whitespace.comment is not None:
        return (
            block.with_changes(body=[first.with_changes(body=[cst.Pass()]), *later]),
            True,
        )
    if first.leading_lines:
        later[0] = _with_leading(later[0], first.leading_lines)
    return block.with_changes(body=later), True


def strip_simple_suite_docstring(
    suite: cst.SimpleStatementSuite,
) -> tuple[cst.SimpleStatementSuite, bool]:
    if not suite.body:
        return suite, False
    first = suite.body[0]
    if not (isinstance(first, cst.Expr) and is_docstring_literal(first.value)):
        return suite, False
    return suite.with_changes(body=list(suite.body[1:]) or [cst.Pass()]), True


def strip_suite_docstring(suite: cst.BaseSuite) -> tuple[cst.BaseSuite, bool]:
    if isinstance(suite, cst.IndentedBlock):
        return strip_indented_block_docstring(suite)
    if isinstance(suite, cst.SimpleStatementSuite):
        return strip_simple_suite_docstring(suite)
    return suite, False


def strip_module_docstring(module: cst.Module) -> cst.Module:
    if not module.body:
        return module
    first = module.body[0]
    if not (isinstance(first, cst.SimpleStatementLine) and starts_with_docstring(first)):
        return module
    tail = list(first.body[1:])
    rest = list(module.body[1:])
    if tail:
        return module.with_changes(body=[first.with_changes(body=tail), *rest])
    if first.leading_lines:
        if rest:
            rest[0] = _with_leading(rest[0], first.leading_lines)
        else:
            return module.with_changes(body=[], header=[*module.header, *first.leading_lines])
    return module.with_changes(body=rest)


class StructureStripper(cst.CSTTransformer):
    def __init__(self, options: TransformOptions) -> None:
        super().__init__()
        self.strip_docs = options.remove_docstrings
        self.strip_types = options.remove_type_annotations
        self.keep_class_annotations = not options.strip_class_annotations
        self.scopes: list[bool] = []

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self.scopes.append(True)

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        self.scopes.append(False)

    def leave_ClassDef(self, original_node, updated_node):
        self.scopes.pop()
        if not self.strip_docs:
            return updated_node
        body, changed = strip_suite_docstring(updated_node.body)
        return updated_node.with_changes(body=body) if changed else updated_node

    def leave_FunctionDef(self, original_node, updated_node):
        self.scopes.pop()
        if self.strip_docs:
            body, changed = strip_suite_docstring(updated_node.body)
            if changed:
                updated_node = updated_node.with_changes(body=body)
        if self.strip_types and updated_node.returns is not None:
            updated_node = updated_node.with_changes(returns=None, whitespace_before_colon=cst.SimpleWhitespace(""))
        return updated_node

    def leave_Param(self, original_node, updated_node):
        if self.strip_types and updated_node.annotation is not None:
            return updated_node.with_changes(annotation=None)
        return updated_node

    def leave_AnnAssign(self, original_node, updated_node):
        if not self.strip_types:
            return updated_node
        if self.keep_class_annotations and self.scopes and self.scopes[-1]:
            return updated_node
        if updated_node.value is None:
            return cst.Pass(semicolon=updated_node.semicolon)
        return cst.Assign(
            targets=[cst.AssignTarget(target=updated_node.target)],
            value=updated_node.value,
            semicolon=updated_node.semicolon,
        )


def _has_code_intent(statement: ast.stmt) -> bool:
    if isinstance(statement, ast.AnnAssign) and statement.value is None:
        return False
    if isinstance(statement, ast.Expr):
        return not isinstance(statement.value, (ast.Name, ast.Constant))
    return True


def looks_like_commented_out_code(comment_texts: Sequence[str]) -> bool:
    candidate = textwrap.dedent("\n".join(text[1:].removeprefix(" ") for text in comment_texts))
    if not candidate.strip():
        return False
    attempts = [candidate]
    if candidate.rstrip().endswith(":"):
        attempts.append(candidate + "\n    pass\n")
    for text in attempts:
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError, MemoryError, RecursionError):
            continue
        if any(_has_code_intent(statement) for statement in tree.body):
            return True
    return False


def commented_code_rows(comments: Sequence[tokenize.TokenInfo], lines: Sequence[str]) -> frozenset[int]:
    protected: set[int] = set()
    rows: list[int] = []
    texts: list[str] = []
    last = -2

    def flush() -> None:
        if texts and looks_like_commented_out_code(texts):
            protected.update(rows)
        rows.clear()
        texts.clear()

    for token in comments:
        row, col = token.start
        standalone = not lines[row - 1][:col].strip()
        if not standalone or PROTECTED_COMMENT_RE.match(token.string):
            flush()
            last = -2
            continue
        if row != last + 1:
            flush()
        rows.append(row)
        texts.append(token.string)
        last = row
    flush()
    return frozenset(protected)


def strip_comments(source: str, options: TransformOptions) -> str | None:
    if "#" not in source:
        return source
    try:
        comments = [
            token for token in tokenize.generate_tokens(io.StringIO(source).readline) if token.type == tokenize.COMMENT
        ]
    except (SyntaxError, tokenize.TokenError, ValueError):
        return None
    if not comments:
        return source
    lines = source.split("\n")
    protected_rows = _NO_LINES
    if options.remove_all_comments and not options.remove_all and not options.remove_commented_code:
        protected_rows = commented_code_rows(comments, lines)
    drop_type_comments = options.remove_type_annotations
    changed = False
    for token in comments:
        row, col = token.start
        text = token.string
        line = lines[row - 1]
        if not line.startswith(text, col):
            return None
        prefix = line[:col]
        standalone = not prefix.strip()
        if standalone and ((row == 1 and text.startswith("#!")) or (row <= 2 and CODING_RE.match(line))):
            continue
        if drop_type_comments and TYPE_COMMENT_RE.match(text):
            remove = True
        elif options.remove_all:
            remove = True
        elif PROTECTED_COMMENT_RE.match(text):
            remove = False
        elif standalone:
            remove = options.remove_all_comments and row not in protected_rows
        else:
            remove = True
        if not remove:
            continue
        carriage_return = "\r" if line.endswith("\r") else ""
        lines[row - 1] = carriage_return if standalone else prefix.rstrip(" \t\f") + carriage_return
        changed = True
    return "\n".join(lines) if changed else source


def multiline_string_lines(source: str) -> frozenset[int] | None:
    occupied: set[int] = set()
    depth = 0
    start_line = 0
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            kind = token.type
            if kind == tokenize.STRING:
                if token.end[0] > token.start[0]:
                    occupied.update(range(token.start[0], token.end[0] + 1))
            elif kind in _STRING_STARTS:
                if depth == 0:
                    start_line = token.start[0]
                depth += 1
            elif kind in _STRING_ENDS:
                depth -= 1
                if depth == 0 and token.end[0] > start_line:
                    occupied.update(range(start_line, token.end[0] + 1))
    except (SyntaxError, tokenize.TokenError, ValueError):
        return None
    return frozenset(occupied)


def collapse_repeated_blank_lines(source: str) -> str:
    if BLANK_RUN_RE.search(source) is None:
        return source
    if '"""' in source or "'''" in source:
        protected = multiline_string_lines(source)
        if protected is None:
            return source
    else:
        protected = _NO_LINES
    parts = source.split("\n")
    tail = parts.pop()
    kept: list[str] = []
    previous_blank = False
    for number, part in enumerate(parts, 1):
        blank = number not in protected and not part.strip(" \t\r")
        if blank and previous_blank:
            continue
        kept.append(part)
        previous_blank = blank
    kept.append(tail)
    return "\n".join(kept)


def atomic_replace(path: Path, data: bytes, fsync: bool, mode_source: Path | None = None) -> None:
    try:
        mode = os.stat(mode_source or path).st_mode & 0o7777
    except OSError:
        mode = None
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            if fsync:
                stream.flush()
                os.fsync(stream.fileno())
        if mode is not None:
            with contextlib.suppress(OSError):
                os.chmod(temporary_name, mode)
        os.replace(temporary_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary_name)
        raise


def backup_path_for(path: Path) -> Path:
    return path.with_name(path.name + BACKUP_SUFFIX)


def write_backup(path: Path, data: bytes, overwrite: bool, fsync: bool) -> None:
    backup = backup_path_for(path)
    if backup.exists() and not overwrite:
        raise FileExistsError(f"backup already exists: {backup} (use --overwrite-backup)")
    atomic_replace(backup, data, fsync, mode_source=path)


def restore_from_backup(path: Path, dry_run: bool, fsync: bool) -> tuple[bool, str | None]:
    backup = backup_path_for(path)
    if not backup.exists():
        return False, None
    if dry_run:
        return True, None
    try:
        atomic_replace(path, backup.read_bytes(), fsync)
        backup.unlink(missing_ok=True)
    except OSError as exc:
        return False, f"restore error: {exc}"
    return True, None


def _process_file(path: Path, options: TransformOptions) -> FileResult:
    try:
        with open(path, "rb") as stream:
            before = os.fstat(stream.fileno())
            original = stream.read()
    except OSError as exc:
        return FileResult(path, error=f"read error: {exc}")
    size = len(original)
    if not size:
        return FileResult(path)
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(original).readline)
        source = original.decode(encoding)
    except (SyntaxError, UnicodeDecodeError, LookupError) as exc:
        return FileResult(path, size, error=f"encoding error: {exc}")
    new_source = strip_comments(source, options)
    if new_source is None:
        return FileResult(path, size, error="tokenize error: cannot locate comments safely")
    effective = options
    if "__doc__" in source and (options.remove_docstrings or options.remove_module_docstring):
        effective = dataclasses.replace(options, remove_docstrings=False, remove_module_docstring=False)
    docs_wanted = (effective.remove_docstrings or effective.remove_module_docstring) and (
        '"' in new_source or "'" in new_source
    )
    if docs_wanted or effective.remove_type_annotations:
        try:
            module = cst.parse_module(new_source)
        except cst.ParserSyntaxError as exc:
            return FileResult(path, size, error=f"LibCST parse error: {exc}")
        except Exception as exc:
            return FileResult(path, size, error=f"parse error: {type(exc).__name__}: {exc}")
        try:
            module = module.visit(StructureStripper(effective))
            if effective.remove_module_docstring:
                module = strip_module_docstring(module)
            new_source = module.code
        except Exception as exc:
            return FileResult(path, size, error=f"transform error: {type(exc).__name__}: {exc}")
    if options.collapse_blank_lines:
        new_source = collapse_repeated_blank_lines(new_source)
    if new_source == source:
        return FileResult(path, size, size)
    try:
        new_bytes = new_source.encode(encoding)
    except UnicodeEncodeError as exc:
        return FileResult(path, size, error=f"encoding error: {exc}")
    try:
        ast.parse(new_source, filename=str(path), type_comments=True)
    except (SyntaxError, ValueError, MemoryError, RecursionError) as exc:
        return FileResult(path, size, len(new_bytes), error=f"post-transform validation failed: {exc}")
    if not options.dry_run:
        try:
            after = os.stat(path)
        except OSError as exc:
            return FileResult(path, size, len(new_bytes), error=f"write error: {exc}")
        if (after.st_mtime_ns, after.st_size) != (before.st_mtime_ns, before.st_size):
            return FileResult(
                path,
                size,
                len(new_bytes),
                error="file changed while processing; left untouched",
            )
        if options.make_backup:
            try:
                write_backup(path, original, options.overwrite_backup, options.fsync)
            except OSError as exc:
                return FileResult(path, size, len(new_bytes), error=f"backup error: {exc}")
        try:
            atomic_replace(path, new_bytes, options.fsync)
        except OSError as exc:
            return FileResult(path, size, len(new_bytes), error=f"write error: {exc}")
    return FileResult(path, size, len(new_bytes), changed=True)


def process_file(path: Path, options: TransformOptions) -> FileResult:
    try:
        return _process_file(path, options)
    except Exception as exc:
        return FileResult(path, error=f"unexpected error: {type(exc).__name__}: {exc}")


# ----------------------------------------------------------------------------- discovery
def has_python_shebang(path: str) -> bool:
    try:
        with open(path, "rb") as stream:
            head = stream.readline(256)
    except OSError:
        return False
    return head.startswith(b"#!") and b"python" in head


def _accept_python(name: str, path: str) -> bool:
    if name.endswith(PY_SUFFIXES):
        return True
    return not os.path.splitext(name)[1] and has_python_shebang(path)


def _accept_backup(name: str, path: str) -> bool:
    return name.endswith(BACKUP_SUFFIX)


def _walk(root: str, skip_names: frozenset[str] | set[str], accept: Callable[[str, str], bool]) -> Iterator[str]:
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = list(iterator)
        except OSError as exc:
            warn(f"cannot scan {directory}: {exc}")
            continue
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                name = entry.name
                if entry.is_dir(follow_symlinks=False):
                    if name not in skip_names and not name.endswith(".egg-info"):
                        stack.append(entry.path)
                elif entry.is_file(follow_symlinks=False) and accept(name, entry.path):
                    yield entry.path
            except OSError as exc:
                warn(f"cannot inspect {entry.path}: {exc}")


def iter_python_files(paths: Iterable[Path], extra_excludes: Sequence[str]) -> Iterator[Path]:
    seen: set[str] = set()
    skip_names = DEFAULT_SKIP_DIR_NAMES.union(extra_excludes)
    for given in paths:
        try:
            if os.path.isdir(given):
                candidates: Iterable[str] = _walk(os.path.realpath(given), skip_names, _accept_python)
            elif os.path.isfile(given):
                if not (given.name.endswith(PY_SUFFIXES) or not given.suffix):
                    warn(f"skipping non-Python file: {given}")
                    continue
                candidates = (os.path.realpath(given),)
            else:
                warn(f"skipping non-existent path: {given}")
                continue
            for candidate in candidates:
                if candidate not in seen:
                    seen.add(candidate)
                    yield Path(candidate)
        except OSError as exc:
            warn(f"cannot access {given}: {exc}")


def iter_backup_targets(paths: Iterable[Path], extra_excludes: Sequence[str]) -> Iterator[Path]:
    seen: set[str] = set()
    skip_names = DEFAULT_SKIP_DIR_NAMES.union(extra_excludes)
    for given in paths:
        try:
            if os.path.isdir(given):
                originals = (
                    p[: -len(BACKUP_SUFFIX)] for p in _walk(os.path.realpath(given), skip_names, _accept_backup)
                )
            elif os.path.isfile(given):
                real = os.path.realpath(given)
                if real.endswith(BACKUP_SUFFIX):
                    originals = (real[: -len(BACKUP_SUFFIX)],)
                elif os.path.exists(real + BACKUP_SUFFIX):
                    originals = (real,)
                else:
                    originals = ()
            else:
                warn(f"skipping non-existent path: {given}")
                continue
            for original in originals:
                if original not in seen:
                    seen.add(original)
                    yield Path(original)
        except OSError as exc:
            warn(f"cannot access {given}: {exc}")


# ----------------------------------------------------------------------------- CLI
def default_jobs() -> int:
    try:
        count = len(os.sched_getaffinity(0))
    except AttributeError:
        count = os.cpu_count() or 1
    return max(1, min(DEFAULT_MAX_PROCESSES, count))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="Safely strip Python comments, docstrings, annotations, and repeated blank lines.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="remove all comments (except shebang/encoding cookie) and all docstrings; combine with -t for annotations",
    )
    parser.add_argument(
        "-c",
        "--remove-all-comments",
        action="store_true",
        help="also remove standalone comments; directives and commented-out code remain unless --all / --remove-commented-code",
    )
    parser.add_argument(
        "-d",
        "--remove-docstrings",
        action="store_true",
        help="remove function/class docstrings, preserving the module docstring",
    )
    parser.add_argument(
        "-t",
        "--type",
        dest="remove_type_annotations",
        action="store_true",
        help="remove parameter, return, variable annotations and '# type:' comments (class-body annotations are kept)",
    )
    parser.add_argument(
        "--strip-class-annotations",
        action="store_true",
        help="with -t, also strip class-body annotations (breaks dataclass/NamedTuple/TypedDict/pydantic)",
    )
    parser.add_argument(
        "--remove-commented-code",
        action="store_true",
        help="remove comments that parse as Python instead of protecting them",
    )
    parser.add_argument(
        "--keep-blank-lines",
        action="store_true",
        help="do not collapse runs of repeated blank lines",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help=f"save original bytes beside each changed file as *{BACKUP_SUFFIX}",
    )
    parser.add_argument(
        "--overwrite-backup",
        action="store_true",
        help="allow --backup to replace an existing backup",
    )
    parser.add_argument("--reverse", action="store_true", help="restore files from sidecar backups")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show changes without writing files or backups",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="like --dry-run, but return status 3 if any file would change",
    )
    parser.add_argument(
        "--fsync",
        action="store_true",
        help="fsync every written file (durable but much slower)",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=default_jobs(),
        metavar="N",
        help="worker processes (default: min(8, usable CPUs); 1 disables multiprocessing)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        metavar="N",
        help=f"maximum multiprocessing chunk size (default: {DEFAULT_CHUNK_SIZE})",
    )
    parser.add_argument(
        "--exclude-dir",
        action="append",
        default=["lazy", "pip", "numpy", "pandas", "scipy", "setuptools", "numba"],
        metavar="NAME",
        help="additional directory basename to skip; repeatable",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="disable ANSI color (NO_COLOR is also honored)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="print only errors and the final summary",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        metavar="PATH",
        help="files/directories; default: current directory",
    )
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    if args.chunk_size < 1:
        parser.error("--chunk-size must be at least 1")
    if args.overwrite_backup and not args.backup:
        parser.error("--overwrite-backup requires --backup")
    if args.reverse and args.backup:
        parser.error("--reverse cannot be combined with --backup")


# ----------------------------------------------------------------------------- execution
_WORKER_OPTIONS: TransformOptions | None = None


def _init_worker(options: TransformOptions) -> None:
    global _WORKER_OPTIONS
    _WORKER_OPTIONS = options
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def _worker(path: Path) -> FileResult:
    return process_file(path, _WORKER_OPTIONS)  # type: ignore[arg-type]


def _file_size(path: Path) -> int:
    try:
        return os.stat(path).st_size
    except OSError:
        return 0


def iter_results(files: list[Path], options: TransformOptions, jobs: int, chunk_size: int) -> Iterator[FileResult]:
    if jobs == 1 or len(files) < PARALLEL_MIN_FILES:
        for path in files:
            yield process_file(path, options)
        return
    files.sort(key=_file_size, reverse=True)
    chunk = max(1, min(chunk_size, len(files) // (jobs * 4)))
    with mp.Pool(
        processes=jobs,
        initializer=_init_worker,
        initargs=(options,),
        maxtasksperchild=500,
    ) as pool:
        yield from pool.imap_unordered(_worker, files, chunksize=chunk)


def run_reverse(paths: Sequence[Path], args: argparse.Namespace) -> int:
    targets = list(iter_backup_targets(paths, args.exclude_dir))
    if not targets:
        emit("No backup files found to restore.", file=sys.stderr)
        return 1
    dry = args.dry_run or args.check
    restored = errors = 0
    for path in targets:
        changed, error = restore_from_backup(path, dry, args.fsync)
        if error:
            errors += 1
            emit(f"{display_path(path)}: {error}", file=sys.stderr)
        elif changed:
            restored += 1
            if not args.quiet:
                emit(f"{display_path(path)}  {'would restore' if dry else 'restored'}")
    emit(f"\n{'Would restore' if dry else 'Restored'} {restored} file(s), {errors} error(s).")
    if errors:
        return 2
    return 3 if args.check and restored else 0


def run_strip(paths: Sequence[Path], args: argparse.Namespace) -> int:
    dry_run = args.dry_run or args.check
    options = TransformOptions(
        remove_all=args.all,
        remove_all_comments=args.all or args.remove_all_comments,
        remove_docstrings=args.all or args.remove_docstrings,
        remove_module_docstring=args.all,
        remove_type_annotations=args.remove_type_annotations,
        strip_class_annotations=args.strip_class_annotations,
        remove_commented_code=args.remove_commented_code,
        collapse_blank_lines=not args.keep_blank_lines,
        make_backup=args.backup,
        overwrite_backup=args.overwrite_backup,
        fsync=args.fsync,
        dry_run=dry_run,
    )
    files = list(iter_python_files(paths, args.exclude_dir))
    if not files:
        emit("No Python files found.", file=sys.stderr)
        return 1
    jobs = min(args.jobs, len(files))
    use_color = not args.no_color and not os.environ.get("NO_COLOR") and sys.stdout.isatty()
    color, reset = (GREEN, RESET) if use_color else ("", "")
    action = "would reduce" if dry_run else "reduced"
    total = changed = errors = old_total = new_total = 0
    for result in iter_results(files, options, jobs, args.chunk_size):
        total += 1
        if result.error:
            errors += 1
            emit(f"{display_path(result.path)}: {result.error}", file=sys.stderr)
            continue
        if not result.changed:
            continue
        changed += 1
        old_total += result.old_size
        new_total += result.new_size
        if not args.quiet:
            emit(f"{display_path(result.path)}  {action} {color}{format_size(result.bytes_reduced)}{reset}")
    verb = "would change" if dry_run else "changed"
    summary = (
        f"\nProcessed {total} file(s): {verb} {changed}, "
        f"{color}{format_size(old_total - new_total)}{reset} reduced, {errors} error(s)."
    )
    emit(summary, file=sys.stderr if errors else None)
    if errors:
        return 2
    return 3 if args.check and changed else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    validate_args(parser, args)
    paths = args.paths or [Path.cwd()]
    try:
        return run_reverse(paths, args) if args.reverse else run_strip(paths, args)
    except KeyboardInterrupt:
        emit("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
