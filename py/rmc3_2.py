#!/data/data/com.termux/files/usr/bin/python

from __future__ import annotations
import argparse
import ast
import contextlib
from dataclasses import dataclass
import functools
import io
import multiprocessing as mp
import os
from pathlib import Path
import re
import sys
import tempfile
import tokenize
from typing import Iterable, Iterator, Sequence

import libcst as cst


PROGRAM = "strip_comments"
VERSION = "2.0.0"
DEFAULT_MAX_PROCESSES = 8
DEFAULT_CHUNK_SIZE = 8
PY_SUFFIXES = (".py", ".pyi")
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
    r"^#(?:!|\s*(?:-\*-.*coding|coding[:=]|fmt\b|type\b|noqa\b|pylint\b|"
    r"ruff\b|isort\b|mypy\b|pyright\b|pragma\b))",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class TransformOptions:
    remove_all: bool
    remove_all_comments: bool
    remove_docstrings: bool
    remove_type_annotations: bool
    remove_commented_code: bool
    collapse_blank_lines: bool
    make_backup: bool
    overwrite_backup: bool
    dry_run: bool

    def __post_init__(self) -> None:
        if self.remove_all:
            object.__setattr__(self, "remove_all_comments", True)
            object.__setattr__(self, "remove_docstrings", True)


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


def has_trailing_comment(node: cst.CSTNode) -> bool:
    whitespace = getattr(node, "trailing_whitespace", None)
    return whitespace is not None and getattr(whitespace, "comment", None) is not None


def strip_indented_block_docstring(
    block: cst.IndentedBlock,
) -> tuple[cst.IndentedBlock, bool]:
    if not block.body or not isinstance(block.body[0], cst.SimpleStatementLine):
        return block, False
    first = block.body[0]
    if not starts_with_docstring(first):
        return block, False
    same_line_tail = list(first.body[1:])
    later_statements = list(block.body[1:])
    if same_line_tail:
        return (
            block.with_changes(body=[first.with_changes(body=same_line_tail), *later_statements]),
            True,
        )
    if not later_statements or has_trailing_comment(first):
        return (
            block.with_changes(body=[first.with_changes(body=[cst.Pass()]), *later_statements]),
            True,
        )
    if first.leading_lines:
        following = later_statements[0]
        existing = list(getattr(following, "leading_lines", ()) or ())
        with contextlib.suppress(AttributeError):
            later_statements[0] = following.with_changes(leading_lines=[*first.leading_lines, *existing])
    return block.with_changes(body=later_statements), True


def strip_simple_suite_docstring(
    suite: cst.SimpleStatementSuite,
) -> tuple[cst.SimpleStatementSuite, bool]:
    if not suite.body:
        return suite, False
    first = suite.body[0]
    if not (isinstance(first, cst.Expr) and is_docstring_literal(first.value)):
        return suite, False
    remaining = list(suite.body[1:]) or [cst.Pass()]
    return suite.with_changes(body=remaining), True


def strip_suite_docstring(suite: cst.BaseSuite) -> tuple[cst.BaseSuite, bool]:
    if isinstance(suite, cst.IndentedBlock):
        return strip_indented_block_docstring(suite)
    if isinstance(suite, cst.SimpleStatementSuite):
        return strip_simple_suite_docstring(suite)
    return suite, False


def strip_module_docstring(module: cst.Module) -> cst.Module:
    if not module.body or not isinstance(module.body[0], cst.SimpleStatementLine):
        return module
    first = module.body[0]
    if not starts_with_docstring(first):
        return module
    same_line_tail = list(first.body[1:])
    rest = list(module.body[1:])
    if same_line_tail:
        return module.with_changes(body=[first.with_changes(body=same_line_tail), *rest])
    if first.leading_lines and rest:
        following = rest[0]
        existing = list(getattr(following, "leading_lines", ()) or ())
        with contextlib.suppress(AttributeError):
            rest[0] = following.with_changes(leading_lines=[*first.leading_lines, *existing])
    elif first.leading_lines:
        return module.with_changes(body=[], header=[*module.header, *first.leading_lines])
    return module.with_changes(body=rest)


def _dehash(comment: str) -> str:
    text = comment[1:]
    return text.removeprefix(" ")


def looks_like_commented_out_code(comment_lines: Sequence[str]) -> bool:
    candidate = "\n".join(_dehash(line) for line in comment_lines)
    if not candidate.strip():
        return False
    try:
        tree = ast.parse(candidate)
    except (SyntaxError, ValueError, MemoryError):
        return False

    def has_code_intent(statement: ast.stmt) -> bool:
        if not isinstance(statement, ast.Expr):
            return True
        return not isinstance(statement.value, (ast.Name, ast.Constant))

    return any(has_code_intent(statement) for statement in tree.body)


def find_commented_out_code_lines(source: str) -> frozenset[int]:
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    except (IndentationError, tokenize.TokenError, SyntaxError):
        return frozenset()
    protected: set[int] = set()
    lines: list[int] = []
    texts: list[str] = []
    previous: int | None = None

    def flush() -> None:
        if texts and looks_like_commented_out_code(texts):
            protected.update(lines)

    for token in comments:
        line_number, column = token.start
        prefix = token.line[:column]
        is_full_line = not prefix.strip()
        is_directive = PROTECTED_COMMENT_RE.match(token.string) is not None
        if not is_full_line or is_directive:
            flush()
            lines.clear()
            texts.clear()
            previous = None
            continue
        if previous is not None and line_number != previous + 1:
            flush()
            lines.clear()
            texts.clear()
        lines.append(line_number)
        texts.append(token.string)
        previous = line_number
    flush()
    return frozenset(protected)


class CommentDocstringStripper(cst.CSTTransformer):
    def __init__(self, options: TransformOptions, protected_code_lines: frozenset[int]):
        super().__init__()
        self.options = options
        self.protected_code_lines = protected_code_lines

    @staticmethod
    def _is_protected_directive(text: str) -> bool:
        return PROTECTED_COMMENT_RE.match(text) is not None

    def _is_on_protected_line(self, node: cst.CSTNode) -> bool:
        return False

    def _should_remove_comment(self, comment: cst.Comment) -> bool:
        if self.protected_code_lines and self._is_on_protected_line(comment):
            return False
        if self.options.remove_all:
            return True
        return not self._is_protected_directive(comment.value)

    def leave_TrailingWhitespace(self, original_node, updated_node):
        del original_node
        comment = updated_node.comment
        if comment is None or not self._should_remove_comment(comment):
            return updated_node
        return updated_node.with_changes(whitespace=cst.SimpleWhitespace(""), comment=None)

    def leave_EmptyLine(self, original_node, updated_node):
        del original_node
        comment = updated_node.comment
        if not self.options.remove_all_comments or comment is None or not self._should_remove_comment(comment):
            return updated_node
        return updated_node.with_changes(comment=None)

    def leave_FunctionDef(self, original_node, updated_node):
        del original_node
        if self.options.remove_docstrings:
            body, changed = strip_suite_docstring(updated_node.body)
            if changed:
                updated_node = updated_node.with_changes(body=body)
        if self.options.remove_type_annotations:
            changes: dict[str, object] = {"returns": None}
            if getattr(updated_node, "type_comment", None) is not None:
                changes["type_comment"] = None
            updated_node = updated_node.with_changes(**changes)
        return updated_node

    def leave_ClassDef(self, original_node, updated_node):
        del original_node
        if not self.options.remove_docstrings:
            return updated_node
        body, changed = strip_suite_docstring(updated_node.body)
        return updated_node.with_changes(body=body) if changed else updated_node

    def leave_Param(self, original_node, updated_node):
        del original_node
        if self.options.remove_type_annotations and updated_node.annotation is not None:
            return updated_node.with_changes(annotation=None)
        return updated_node

    def leave_AnnAssign(self, original_node, updated_node):
        del original_node
        if not self.options.remove_type_annotations:
            return updated_node
        if updated_node.value is None:
            return cst.Pass()
        return cst.Assign(
            targets=[cst.AssignTarget(target=updated_node.target)],
            value=updated_node.value,
        )

    def leave_Assign(self, original_node, updated_node):
        del original_node
        if self.options.remove_type_annotations and getattr(updated_node, "type_comment", None) is not None:
            return updated_node.with_changes(type_comment=None)
        return updated_node

    def leave_For(self, original_node, updated_node):
        del original_node
        if self.options.remove_type_annotations and getattr(updated_node, "type_comment", None) is not None:
            return updated_node.with_changes(type_comment=None)
        return updated_node

    def leave_With(self, original_node, updated_node):
        del original_node
        if self.options.remove_type_annotations and getattr(updated_node, "type_comment", None) is not None:
            return updated_node.with_changes(type_comment=None)
        return updated_node


class PositionAwareStripper(CommentDocstringStripper):
    METADATA_DEPENDENCIES = (cst.metadata.PositionProvider,)

    def _is_on_protected_line(self, node: cst.CSTNode) -> bool:
        position = self.get_metadata(cst.metadata.PositionProvider, node, None)
        return position is not None and position.start.line in self.protected_code_lines


def run_transform(
    module: cst.Module,
    options: TransformOptions,
    protected_code_lines: frozenset[int],
) -> cst.Module:
    transformer_type = PositionAwareStripper if protected_code_lines else CommentDocstringStripper
    transformer = transformer_type(options, protected_code_lines)
    if protected_code_lines:
        return cst.metadata.MetadataWrapper(module).visit(transformer)
    return module.visit(transformer)


def string_token_lines(source: str) -> set[int]:
    occupied: set[int] = set()
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.STRING:
                occupied.update(range(token.start[0], token.end[0] + 1))
    except (IndentationError, tokenize.TokenError):
        return set()
    return occupied


def collapse_repeated_blank_lines(source: str) -> str:
    lines = source.splitlines(keepends=True)
    strings = string_token_lines(source)
    result: list[str] = []
    previous_blank = False
    for line_number, line in enumerate(lines, 1):
        blank = not line.strip() and line_number not in strings
        if blank and previous_blank:
            continue
        result.append(line)
        previous_blank = blank
    return "".join(result)


def atomic_replace(path: Path, data: bytes) -> None:
    try:
        mode = path.stat().st_mode
    except OSError:
        mode = None
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            with contextlib.suppress(OSError):
                os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            temporary.unlink()
        raise


def backup_path_for(path: Path) -> Path:
    return path.with_name(path.name + BACKUP_SUFFIX)


def write_backup(path: Path, data: bytes, overwrite: bool) -> None:
    backup = backup_path_for(path)
    if backup.exists() and not overwrite:
        msg = f"backup already exists: {backup} (use --overwrite-backup)"
        raise FileExistsError(msg)
    atomic_replace(backup, data)


def restore_from_backup(path: Path, dry_run: bool = False) -> tuple[bool, str | None]:
    backup = backup_path_for(path)
    if not backup.exists():
        return False, None
    if dry_run:
        return True, None
    try:
        data = backup.read_bytes()
        atomic_replace(path, data)
        backup.unlink(missing_ok=True)
    except OSError as exc:
        return False, f"restore error: {exc}"
    return True, None


def process_file(path: Path, options: TransformOptions) -> FileResult:
    try:
        original_bytes = path.read_bytes()
    except OSError as exc:
        return FileResult(path, error=f"read error: {exc}")
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(original_bytes).readline)
        source = original_bytes.decode(encoding)
    except (SyntaxError, UnicodeDecodeError) as exc:
        return FileResult(path, len(original_bytes), error=f"encoding error: {exc}")
    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError as exc:
        return FileResult(path, len(original_bytes), error=f"LibCST parse error: {exc}")
    except Exception as exc:
        return FileResult(path, len(original_bytes), error=f"parse error: {type(exc).__name__}: {exc}")
    protected_lines = frozenset() if options.remove_commented_code else find_commented_out_code_lines(source)
    try:
        transformed = run_transform(module, options, protected_lines)
        if options.remove_all:
            transformed = strip_module_docstring(transformed)
        new_source = transformed.code
        if options.collapse_blank_lines:
            new_source = collapse_repeated_blank_lines(new_source)
        new_bytes = new_source.encode(encoding)
    except Exception as exc:
        return FileResult(
            path,
            len(original_bytes),
            error=f"transform error: {type(exc).__name__}: {exc}",
        )
    if new_bytes == original_bytes:
        return FileResult(path, len(original_bytes), len(original_bytes))
    try:
        ast.parse(new_source, filename=str(path), type_comments=True)
    except (SyntaxError, ValueError) as exc:
        return FileResult(
            path,
            len(original_bytes),
            len(new_bytes),
            error=f"post-transform validation failed: {exc}",
        )
    if not options.dry_run:
        if options.make_backup:
            try:
                write_backup(path, original_bytes, options.overwrite_backup)
            except OSError as exc:
                return FileResult(
                    path,
                    len(original_bytes),
                    len(new_bytes),
                    error=f"backup error: {exc}",
                )
        try:
            atomic_replace(path, new_bytes)
        except (OSError, UnicodeEncodeError) as exc:
            return FileResult(path, len(original_bytes), len(new_bytes), error=f"write error: {exc}")
    return FileResult(path, len(original_bytes), len(new_bytes), changed=True)


def _walk_python_files(root: Path, skip_names: frozenset[str]) -> Iterator[Path]:
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name not in skip_names:
                                stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False) and entry.name.endswith(PY_SUFFIXES):
                            yield Path(entry.path)
                    except OSError as exc:
                        print(
                            f"warning: cannot inspect {entry.path}: {exc}",
                            file=sys.stderr,
                        )
        except OSError as exc:
            print(f"warning: cannot scan {directory}: {exc}", file=sys.stderr)


def iter_python_files(paths: Iterable[Path], extra_excludes: Sequence[str]) -> Iterator[Path]:
    seen: set[Path] = set()
    skip_names = DEFAULT_SKIP_DIR_NAMES.union(extra_excludes)
    for given in paths:
        try:
            if given.is_file():
                candidates: Iterable[Path] = (given,) if given.name.endswith(PY_SUFFIXES) else ()
            elif given.is_dir():
                candidates = _walk_python_files(given, skip_names)
            else:
                print(f"warning: skipping non-existent path: {given}", file=sys.stderr)
                continue
            for candidate in candidates:
                try:
                    resolved = candidate.resolve()
                except OSError:
                    continue
                if resolved not in seen:
                    seen.add(resolved)
                    yield candidate
        except OSError as exc:
            print(f"warning: cannot access {given}: {exc}", file=sys.stderr)


def iter_backup_targets(paths: Iterable[Path], extra_excludes: Sequence[str]) -> Iterator[Path]:
    seen: set[Path] = set()
    skip_names = DEFAULT_SKIP_DIR_NAMES.union(extra_excludes)
    for given in paths:
        if given.is_file():
            candidates = [given] if given.name.endswith(BACKUP_SUFFIX) else []
        elif given.is_dir():
            candidates = []
            stack = [given]
            while stack:
                directory = stack.pop()
                try:
                    with os.scandir(directory) as entries:
                        for entry in entries:
                            if entry.is_dir(follow_symlinks=False) and entry.name not in skip_names:
                                stack.append(Path(entry.path))
                            elif entry.is_file(follow_symlinks=False) and entry.name.endswith(BACKUP_SUFFIX):
                                candidates.append(Path(entry.path))
                except OSError as exc:
                    print(f"warning: cannot scan {directory}: {exc}", file=sys.stderr)
        else:
            print(f"warning: skipping non-existent path: {given}", file=sys.stderr)
            continue
        for backup in candidates:
            original = backup.with_name(backup.name[: -len(BACKUP_SUFFIX)])
            try:
                key = original.resolve()
            except OSError:
                key = original.absolute()
            if key not in seen:
                seen.add(key)
                yield original


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="Safely strip Python comments, docstrings, annotations, and repeated blank lines with LibCST.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="remove all comments and all docstrings; combine with -t for annotations",
    )
    parser.add_argument(
        "-c",
        "--remove-all-comments",
        action="store_true",
        help="also remove standalone comments; protected directives remain unless --all",
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
        help="remove parameter, return, variable, and supported type-comment annotations",
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
        "-j",
        "--jobs",
        type=int,
        default=min(DEFAULT_MAX_PROCESSES, os.cpu_count() or 1),
        metavar="N",
        help="worker processes (default: min(8, CPU count); 1 disables multiprocessing)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        metavar="N",
        help=f"multiprocessing task chunk size (default: {DEFAULT_CHUNK_SIZE})",
    )
    parser.add_argument(
        "--exclude-dir",
        action="append",
        default=[],
        metavar="NAME",
        help="additional directory basename to skip; repeatable",
    )
    parser.add_argument("--no-color", action="store_true", help="disable ANSI color")
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


def run_reverse(paths: Sequence[Path], args: argparse.Namespace) -> int:
    targets = list(iter_backup_targets(paths, args.exclude_dir))
    if not targets:
        print("No backup files found to restore.", file=sys.stderr)
        return 1
    restored = errors = 0
    for path in targets:
        changed, error = restore_from_backup(path, args.dry_run or args.check)
        if error:
            errors += 1
            print(f"{path.name}: {error}", file=sys.stderr)
        elif changed:
            restored += 1
            if not args.quiet:
                action = "would restore" if args.dry_run or args.check else "restored"
                print(f"{path.name}  {action}")
    print(f"\n{'Would restore' if args.dry_run or args.check else 'Restored'} {restored} file(s), {errors} error(s).")
    if errors:
        return 2
    return 3 if args.check and restored else 0


def _result_iterator(
    files: Iterable[Path], options: TransformOptions, jobs: int, chunk_size: int
) -> Iterator[FileResult]:
    worker = functools.partial(process_file, options=options)
    if jobs == 1:
        yield from map(worker, files)
        return
    with mp.Pool(processes=jobs, maxtasksperchild=500) as pool:
        yield from pool.imap_unordered(worker, files, chunksize=chunk_size)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    validate_args(parser, args)
    paths = args.paths or [Path.cwd()]
    if args.reverse:
        return run_reverse(paths, args)
    dry_run = args.dry_run or args.check
    options = TransformOptions(
        remove_all=args.all,
        remove_all_comments=args.all or args.remove_all_comments,
        remove_docstrings=args.all or args.remove_docstrings,
        remove_type_annotations=args.remove_type_annotations,
        remove_commented_code=args.remove_commented_code,
        collapse_blank_lines=not args.keep_blank_lines,
        make_backup=args.backup,
        overwrite_backup=args.overwrite_backup,
        dry_run=dry_run,
    )
    total = changed = errors = old_total = new_total = 0
    files = iter_python_files(paths, args.exclude_dir)
    for result in _result_iterator(files, options, args.jobs, args.chunk_size):
        total += 1
        if result.error:
            errors += 1
            print(f"{result.path}: {result.error}", file=sys.stderr)
            continue
        if not result.changed:
            continue
        changed += 1
        old_total += result.old_size
        new_total += result.new_size
        if not args.quiet:
            delta = result.bytes_reduced
            color = "" if args.no_color or not sys.stdout.isatty() else GREEN
            reset = "" if not color else RESET
            action = "would reduce" if dry_run else "reduced"
            print(f"{result.path}  {action} {color}{format_size(delta)}{reset}")
    if total == 0:
        print("No Python files found.", file=sys.stderr)
        return 1
    reduction = old_total - new_total
    color = "" if args.no_color or not sys.stdout.isatty() else GREEN
    reset = "" if not color else RESET
    verb = "Would change" if dry_run else "Changed"
    summary = f"\nProcessed {total} file(s): {verb.lower()} {changed}, {color}{format_size(reduction)}{reset} reduced, {errors} error(s)."
    print(summary, file=sys.stderr if errors else sys.stdout)
    if errors:
        return 2
    if args.check and changed:
        return 3
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
