from __future__ import annotations
import argparse
import ast
import functools
import io
import multiprocessing as mp
import os
import sys
import tempfile
import tokenize
from pathlib import Path
from typing import Iterable, Iterator
import libcst as cst

NUM_WORKERS = 8
CHUNKSIZE = 4
PYTHON_SUFFIXES: tuple[str, ...] = (".py", ".pyi")
SKIP_DIRS: frozenset[str] = frozenset({
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
PROTECTED_COMMENT_PREFIXES: tuple[str, ...] = (
    "#!",
    "# -*-",
    "# coding",
    "# fmt",
    "# type",
    "# noqa",
    "# pylint",
    "# ruff",
    "# isort",
    "# mypy",
    "# pyright",
    "# pragma",
)
GREEN = "\033[32m"
RESET = "\033[0m"


def format_bytes(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    for unit, threshold in (("M", 1024**3), ("k", 1024)):
        if num_bytes >= threshold:
            value = num_bytes / threshold
            text = f"{value:.1f}".rstrip("0").rstrip(".")
            return f"{text}{unit}"
    return f"{num_bytes} B"


def _is_docstring_literal(node: cst.BaseExpression) -> bool:
    if isinstance(node, cst.SimpleString):
        return "b" not in node.prefix.lower()
    if isinstance(node, cst.ConcatenatedString):
        return _is_docstring_literal(node.left) and _is_docstring_literal(node.right)
    return False


def _is_docstring_line(line: cst.SimpleStatementLine) -> bool:
    if not line.body:
        return False
    first = line.body[0]
    return isinstance(first, cst.Expr) and _is_docstring_literal(first.value)


def _has_trailing_comment(node: cst.CSTNode) -> bool:
    trailing = getattr(node, "trailing_whitespace", None)
    return trailing is not None and getattr(trailing, "comment", None) is not None


def _strip_docstring_from_block(
    block: cst.IndentedBlock,
) -> tuple[cst.IndentedBlock, bool]:
    if not block.body:
        return block, False
    first = block.body[0]
    if not isinstance(first, cst.SimpleStatementLine):
        return block, False
    if not _is_docstring_line(first):
        return block, False
    remaining_small_statements = list(first.body[1:])
    remaining_lines = list(block.body[1:])
    if remaining_small_statements:
        new_first = first.with_changes(body=remaining_small_statements)
        return block.with_changes(body=[new_first, *remaining_lines]), True
    if not remaining_lines or _has_trailing_comment(first):
        new_first = first.with_changes(body=[cst.Pass()])
        return block.with_changes(body=[new_first, *remaining_lines]), True
    if first.leading_lines:
        next_line = remaining_lines[0]
        old_leading = list(getattr(next_line, "leading_lines", ()) or ())
        new_leading = [*first.leading_lines, *old_leading]
        try:
            remaining_lines[0] = next_line.with_changes(leading_lines=new_leading)
        except AttributeError:
            pass
    return block.with_changes(body=remaining_lines), True


def _strip_docstring_from_suite(
    suite: cst.SimpleStatementSuite,
) -> tuple[cst.SimpleStatementSuite, bool]:
    if not suite.body:
        return suite, False
    first = suite.body[0]
    if not (isinstance(first, cst.Expr) and _is_docstring_literal(first.value)):
        return suite, False
    remaining = list(suite.body[1:])
    if not remaining:
        remaining = [cst.Pass()]
    return suite.with_changes(body=remaining), True


def _strip_docstring(
    body: cst.BaseSuite,
) -> tuple[cst.BaseSuite, bool]:
    if isinstance(body, cst.IndentedBlock):
        return _strip_docstring_from_block(body)
    if isinstance(body, cst.SimpleStatementSuite):
        return _strip_docstring_from_suite(body)
    return body, False


def _strip_module_docstring(
    module: cst.Module,
) -> cst.Module:
    if not module.body:
        return module
    first = module.body[0]
    if not isinstance(first, cst.SimpleStatementLine):
        return module
    if not _is_docstring_line(first):
        return module
    remaining_small_statements = list(first.body[1:])
    remaining_lines = list(module.body[1:])
    if remaining_small_statements:
        new_first = first.with_changes(body=remaining_small_statements)
        return module.with_changes(body=[new_first, *remaining_lines])
    if first.leading_lines and remaining_lines:
        next_line = remaining_lines[0]
        old_leading = list(getattr(next_line, "leading_lines", ()) or ())
        new_leading = [*first.leading_lines, *old_leading]
        try:
            remaining_lines[0] = next_line.with_changes(leading_lines=new_leading)
        except AttributeError:
            pass
    elif first.leading_lines and not remaining_lines:
        header_lines = list(module.header)
        header_lines.extend(first.leading_lines)
        return module.with_changes(
            body=[],
            header=header_lines,
        )
    return module.with_changes(body=remaining_lines)


class SourceTransformer(cst.CSTTransformer):
    def __init__(
        self,
        *,
        remove_all: bool,
        remove_all_comments: bool,
        remove_docstrings: bool,
        remove_type_annotations: bool,
    ) -> None:
        super().__init__()
        self.remove_all = remove_all
        self.remove_all_comments = remove_all_comments or remove_all
        self.remove_docstrings = remove_docstrings or remove_all
        self.remove_type_annotations = remove_type_annotations

    @staticmethod
    def _is_protected_comment(comment: str) -> bool:
        return comment.startswith(PROTECTED_COMMENT_PREFIXES)

    def _should_remove_comment(self, comment: str) -> bool:
        if self.remove_all:
            return True
        return not self._is_protected_comment(comment)

    def leave_TrailingWhitespace(
        self,
        original_node: cst.TrailingWhitespace,
        updated_node: cst.TrailingWhitespace,
    ) -> cst.TrailingWhitespace:
        del original_node
        if updated_node.comment is None:
            return updated_node
        if not self._should_remove_comment(updated_node.comment.value):
            return updated_node
        return updated_node.with_changes(
            whitespace=cst.SimpleWhitespace(""),
            comment=None,
        )

    def leave_EmptyLine(
        self,
        original_node: cst.EmptyLine,
        updated_node: cst.EmptyLine,
    ) -> cst.EmptyLine:
        del original_node
        if not self.remove_all_comments:
            return updated_node
        if updated_node.comment is None:
            return updated_node
        if not self._should_remove_comment(updated_node.comment.value):
            return updated_node
        return updated_node.with_changes(comment=None)

    def leave_FunctionDef(
        self,
        original_node: cst.FunctionDef,
        updated_node: cst.FunctionDef,
    ) -> cst.FunctionDef:
        del original_node
        if self.remove_docstrings:
            new_body, removed = _strip_docstring(updated_node.body)
            if removed:
                updated_node = updated_node.with_changes(body=new_body)
        if self.remove_type_annotations:
            updated_node = updated_node.with_changes(
                returns=None,
                type_comment=None,
            )
        return updated_node

    def leave_ClassDef(
        self,
        original_node: cst.ClassDef,
        updated_node: cst.ClassDef,
    ) -> cst.ClassDef:
        del original_node
        if not self.remove_docstrings:
            return updated_node
        new_body, removed = _strip_docstring(updated_node.body)
        if removed:
            return updated_node.with_changes(body=new_body)
        return updated_node

    def leave_Param(
        self,
        original_node: cst.Param,
        updated_node: cst.Param,
    ) -> cst.Param:
        del original_node
        if not self.remove_type_annotations:
            return updated_node
        if updated_node.annotation is None and updated_node.type_comment is None:
            return updated_node
        return updated_node.with_changes(
            annotation=None,
            type_comment=None,
        )

    def leave_AnnAssign(
        self,
        original_node: cst.AnnAssign,
        updated_node: cst.AnnAssign,
    ) -> cst.BaseSmallStatement:
        del original_node
        if not self.remove_type_annotations:
            return updated_node
        if updated_node.value is None:
            return cst.Pass()
        return cst.Assign(
            targets=[
                cst.AssignTarget(
                    target=updated_node.target,
                )
            ],
            value=updated_node.value,
        )

    def leave_Assign(
        self,
        original_node: cst.Assign,
        updated_node: cst.Assign,
    ) -> cst.Assign:
        del original_node
        if not self.remove_type_annotations:
            return updated_node
        type_comment = getattr(updated_node, "type_comment", None)
        if type_comment is None:
            return updated_node
        return updated_node.with_changes(type_comment=None)

    def leave_For(
        self,
        original_node: cst.For,
        updated_node: cst.For,
    ) -> cst.For:
        del original_node
        if not self.remove_type_annotations:
            return updated_node
        type_comment = getattr(updated_node, "type_comment", None)
        if type_comment is None:
            return updated_node
        return updated_node.with_changes(type_comment=None)

    def leave_With(
        self,
        original_node: cst.With,
        updated_node: cst.With,
    ) -> cst.With:
        del original_node
        if not self.remove_type_annotations:
            return updated_node
        type_comment = getattr(updated_node, "type_comment", None)
        if type_comment is None:
            return updated_node
        return updated_node.with_changes(type_comment=None)


def _string_line_numbers(source: str) -> set[int]:
    protected: set[int] = set()
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type != tokenize.STRING:
                continue
            start_line = token.start[0]
            end_line = token.end[0]
            protected.update(range(start_line, end_line + 1))
    except (IndentationError, tokenize.TokenError):
        return set()
    return protected


def collapse_blank_lines(source: str) -> str:
    lines = source.splitlines(keepends=True)
    protected_string_lines = _string_line_numbers(source)
    result: list[str] = []
    previous_was_blank = False
    for line_number, line in enumerate(lines, start=1):
        is_blank = not line.strip()
        if is_blank and line_number not in protected_string_lines:
            if previous_was_blank:
                continue
            newline = "\n"
            if line.endswith("\r\n"):
                newline = "\r\n"
            elif line.endswith("\r"):
                newline = "\r"
            result.append(newline)
            previous_was_blank = True
            continue
        result.append(line)
        previous_was_blank = False
    return "".join(result)


def _atomic_write(path: Path, data: bytes) -> None:
    try:
        mode = path.stat().st_mode
    except OSError:
        mode = None
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        if mode is not None:
            try:
                os.chmod(temporary_path, mode)
            except OSError:
                pass
        os.replace(temporary_path, path)
    except BaseException:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise


def process_file(
    path: Path,
    *,
    remove_all: bool,
    remove_all_comments: bool,
    remove_docstrings: bool,
    remove_type_annotations: bool,
) -> tuple[Path, int, bool, str | None]:
    try:
        source_bytes = path.read_bytes()
    except OSError as exc:
        return path, 0, False, f"read error: {exc}"
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(source_bytes).readline)
        source = source_bytes.decode(encoding)
    except (SyntaxError, UnicodeDecodeError) as exc:
        return path, 0, False, f"encoding error: {exc}"
    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError as exc:
        return path, 0, False, f"LibCST parse error: {exc}"
    except Exception as exc:
        return (
            path,
            0,
            False,
            f"parse error: {type(exc).__name__}: {exc}",
        )
    transformer = SourceTransformer(
        remove_all=remove_all,
        remove_all_comments=remove_all_comments,
        remove_docstrings=remove_docstrings,
        remove_type_annotations=remove_type_annotations,
    )
    try:
        transformed_module = module.visit(transformer)
        if remove_all:
            transformed_module = _strip_module_docstring(transformed_module)
    except Exception as exc:
        return (
            path,
            0,
            False,
            f"transform error: {type(exc).__name__}: {exc}",
        )
    transformed_source = transformed_module.code
    transformed_source = collapse_blank_lines(transformed_source)
    transformed_bytes = transformed_source.encode(encoding)
    changed = transformed_bytes != source_bytes
    if not changed:
        return path, 0, False, None
    try:
        ast.parse(transformed_source, filename=str(path))
    except SyntaxError as exc:
        return (
            path,
            0,
            False,
            f"post-transform validation failed: {exc}",
        )
    try:
        _atomic_write(path, transformed_bytes)
    except (OSError, UnicodeEncodeError) as exc:
        return (
            path,
            0,
            False,
            f"write error: {exc}",
        )
    bytes_reduced = len(source_bytes) - len(transformed_bytes)
    return path, bytes_reduced, True, None


def iter_python_files(roots: Iterable[Path]) -> Iterator[Path]:
    seen: set[Path] = set()

    def on_error(exc: OSError) -> None:
        print(f"warning: {exc}", file=sys.stderr)

    for root in roots:
        try:
            if root.is_file():
                if root.suffix in PYTHON_SUFFIXES:
                    resolved = root.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        yield root
            elif root.is_dir():
                for directory, directory_names, filenames in root.walk(on_error=on_error):
                    directory_names[:] = [name for name in directory_names if name not in SKIP_DIRS]
                    for filename in filenames:
                        if not filename.endswith(PYTHON_SUFFIXES):
                            continue
                        candidate = directory / filename
                        try:
                            resolved = candidate.resolve()
                        except OSError:
                            continue
                        if resolved in seen:
                            continue
                        seen.add(resolved)
                        yield candidate
            else:
                print(
                    f"warning: skipping non-existent path: {root}",
                    file=sys.stderr,
                )
        except OSError as exc:
            print(
                f"warning: cannot access {root}: {exc}",
                file=sys.stderr,
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="strip_comments",
        description=(
            "Safely remove comments, docstrings, type annotations, and "
            "repeated blank lines from Python files using LibCST."
        ),
    )
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help=(
            "Strip everything: all comments (including protected ones), "
            "all docstrings (including the module docstring), and repeated "
            "blank lines. Combine with -t to also strip type annotations."
        ),
    )
    parser.add_argument(
        "-c",
        "--remove-all-comments",
        action="store_true",
        help=(
            "Remove standalone comments in addition to inline comments. "
            "Protected comments are preserved (unlike --all)."
        ),
    )
    parser.add_argument(
        "-d",
        "--remove-docstrings",
        action="store_true",
        help=("Remove function and class docstrings. The module docstring is preserved (unlike --all)."),
    )
    parser.add_argument(
        "-t",
        "--type",
        dest="remove_type_annotations",
        action="store_true",
        help=(
            "Remove function parameter annotations, return annotations, "
            "variable annotations, and supported type comments."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        metavar="PATH",
        help=("Python files or directories to process. Defaults to the current directory."),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    roots = args.paths or [Path.cwd()]
    remove_all = args.all
    remove_all_comments = args.all or args.remove_all_comments
    remove_docstrings = args.all or args.remove_docstrings
    worker = functools.partial(
        process_file,
        remove_all=remove_all,
        remove_all_comments=remove_all_comments,
        remove_docstrings=remove_docstrings,
        remove_type_annotations=args.remove_type_annotations,
    )
    total_files = 0
    changed_files = 0
    total_bytes_reduced = 0
    error_count = 0
    with mp.Pool(processes=NUM_WORKERS) as pool:
        results = pool.imap_unordered(
            worker,
            iter_python_files(roots),
            chunksize=CHUNKSIZE,
        )
        for path, bytes_reduced, changed, error in results:
            total_files += 1
            if error is not None:
                error_count += 1
                continue
            if not changed:
                continue
            changed_files += 1
            total_bytes_reduced += bytes_reduced
            print(f"{path.name}   {GREEN}{format_bytes(bytes_reduced)}{RESET}")
    if total_files == 0:
        print("No Python files found.", file=sys.stderr)
        return 1
    summary = (
        f"\nProcessed {total_files} file(s): "
        f"{changed_files} changed, "
        f"{GREEN}{format_bytes(total_bytes_reduced)}{RESET} reduced, "
        f"{error_count} error(s)."
    )
    print(summary, file=sys.stderr if error_count else sys.stdout)
    return 2 if error_count else 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
