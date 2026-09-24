"""
Safely remove comments, docstrings, type annotations, and excess blank lines
from Python source files using LibCST.

Examples:

    # Remove inline comments.
    python strip_comments.py file.py

    # Remove all non-protected comments and function/class docstrings.
    python strip_comments.py -a file.py

    # Also remove type annotations.
    python strip_comments.py -a -t src/

    # Process the current directory recursively.
    python strip_comments.py -a -t

Protected content is preserved:

* Shebangs, such as ``#!/usr/bin/env python3``.
* Encoding declarations, such as ``# -*- coding: utf-8 -*-``.
* Tool directives, such as ``# noqa`` and ``# type: ignore``.
* The module-level docstring.
* One blank line between source-code sections.

Files are modified in place only after the transformed source successfully
passes ``ast.parse`` validation.
"""

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

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

NUM_WORKERS = 8
CHUNKSIZE = 4

PYTHON_SUFFIXES: tuple[str, ...] = (".py", ".pyi")

SKIP_DIRS: frozenset[str] = frozenset(
    {
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
    }
)

# These comments may contain instructions required by Python or external tools.
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

# --------------------------------------------------------------------------- #
# Docstring helpers
# --------------------------------------------------------------------------- #


def _is_docstring_literal(node: cst.BaseExpression) -> bool:
    """
    Return whether a CST expression is a valid Python docstring literal.

    Bytes literals and f-strings are not considered docstrings. Concatenated
    string literals are docstrings only when both sides are ordinary strings.
    """
    if isinstance(node, cst.SimpleString):
        return "b" not in node.prefix.lower()

    if isinstance(node, cst.ConcatenatedString):
        return _is_docstring_literal(node.left) and _is_docstring_literal(node.right)

    return False


def _is_docstring_line(line: cst.SimpleStatementLine) -> bool:
    """Return whether a statement line begins with a docstring expression."""
    if not line.body:
        return False

    first = line.body[0]
    return isinstance(first, cst.Expr) and _is_docstring_literal(first.value)


def _has_trailing_comment(node: cst.CSTNode) -> bool:
    """Return whether a CST node has a trailing comment."""
    trailing = getattr(node, "trailing_whitespace", None)
    return trailing is not None and getattr(trailing, "comment", None) is not None


def _strip_docstring_from_block(
    block: cst.IndentedBlock,
) -> tuple[cst.IndentedBlock, bool]:
    """
    Remove the first docstring from an indented suite.

    A ``pass`` statement is inserted when removing the docstring would leave
    an invalid empty function or class body.
    """
    if not block.body:
        return block, False

    first = block.body[0]
    if not isinstance(first, cst.SimpleStatementLine):
        return block, False

    if not _is_docstring_line(first):
        return block, False

    remaining_small_statements = list(first.body[1:])
    remaining_lines = list(block.body[1:])

    # Handles: ``"doc"; statement``.
    if remaining_small_statements:
        new_first = first.with_changes(body=remaining_small_statements)
        return block.with_changes(body=[new_first, *remaining_lines]), True

    # Preserve a trailing comment by retaining the line as ``pass``.
    if not remaining_lines or _has_trailing_comment(first):
        new_first = first.with_changes(body=[cst.Pass()])
        return block.with_changes(body=[new_first, *remaining_lines]), True

    # Transfer leading comments attached to the removed docstring line.
    if first.leading_lines:
        next_line = remaining_lines[0]
        old_leading = list(getattr(next_line, "leading_lines", ()) or ())
        new_leading = [*first.leading_lines, *old_leading]

        try:
            remaining_lines[0] = next_line.with_changes(leading_lines=new_leading)
        except AttributeError:
            # If the node does not support leading_lines, retain the rest
            # rather than failing the entire file transformation.
            pass

    return block.with_changes(body=remaining_lines), True


def _strip_docstring_from_suite(
    suite: cst.SimpleStatementSuite,
) -> tuple[cst.SimpleStatementSuite, bool]:
    """
    Remove the first docstring from a one-line suite.

    For example:

        def function(): "doc"

    becomes:

        def function(): pass
    """
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
    """Remove a leading docstring from an arbitrary CST suite."""
    if isinstance(body, cst.IndentedBlock):
        return _strip_docstring_from_block(body)

    if isinstance(body, cst.SimpleStatementSuite):
        return _strip_docstring_from_suite(body)

    return body, False


# --------------------------------------------------------------------------- #
# CST transformer
# --------------------------------------------------------------------------- #


class SourceTransformer(cst.CSTTransformer):
    """
    Remove selected source constructs from a LibCST tree.

    The module docstring is preserved because only FunctionDef and ClassDef
    bodies are passed through the docstring remover.

    Inline comments are removed by default. Standalone comments are removed
    only when ``remove_all_comments`` is enabled. Protected comments are
    always preserved.
    """

    def __init__(
        self,
        *,
        remove_all_comments: bool,
        remove_docstrings: bool,
        remove_type_annotations: bool,
    ) -> None:
        super().__init__()

        self.remove_all_comments = remove_all_comments
        self.remove_docstrings = remove_docstrings
        self.remove_type_annotations = remove_type_annotations

        self.comments_removed = 0
        self.docstrings_removed = 0
        self.type_annotations_removed = 0

    @staticmethod
    def _is_protected_comment(comment: str) -> bool:
        """Return whether a comment must be preserved."""
        return comment.startswith(PROTECTED_COMMENT_PREFIXES)

    # -- Comment removal --------------------------------------------------- #

    def leave_TrailingWhitespace(
        self,
        original_node: cst.TrailingWhitespace,
        updated_node: cst.TrailingWhitespace,
    ) -> cst.TrailingWhitespace:
        """Remove ordinary inline comments."""
        del original_node

        if updated_node.comment is None:
            return updated_node

        comment_text = updated_node.comment.value
        if self._is_protected_comment(comment_text):
            return updated_node

        self.comments_removed += 1

        return updated_node.with_changes(
            whitespace=cst.SimpleWhitespace(""),
            comment=None,
        )

    def leave_EmptyLine(
        self,
        original_node: cst.EmptyLine,
        updated_node: cst.EmptyLine,
    ) -> cst.EmptyLine:
        """Remove standalone comments when ``--all`` or ``--remove-all-comments`` is used."""
        del original_node

        if not self.remove_all_comments:
            return updated_node

        if updated_node.comment is None:
            return updated_node

        comment_text = updated_node.comment.value
        if self._is_protected_comment(comment_text):
            return updated_node

        self.comments_removed += 1
        return updated_node.with_changes(comment=None)

    # -- Docstring removal ------------------------------------------------- #

    def leave_FunctionDef(
        self,
        original_node: cst.FunctionDef,
        updated_node: cst.FunctionDef,
    ) -> cst.FunctionDef:
        """
        Remove function docstrings and return annotations.

        Parameter annotations are removed separately by ``leave_Param``.
        """
        del original_node

        if self.remove_docstrings:
            new_body, removed = _strip_docstring(updated_node.body)
            if removed:
                self.docstrings_removed += 1
                updated_node = updated_node.with_changes(body=new_body)

        if self.remove_type_annotations:
            updated_node = updated_node.with_changes(
                returns=None,
                type_comment=None,
            )
            self.type_annotations_removed += 1

        return updated_node

    def leave_ClassDef(
        self,
        original_node: cst.ClassDef,
        updated_node: cst.ClassDef,
    ) -> cst.ClassDef:
        """Remove class docstrings while preserving the module docstring."""
        del original_node

        if not self.remove_docstrings:
            return updated_node

        new_body, removed = _strip_docstring(updated_node.body)
        if removed:
            self.docstrings_removed += 1
            return updated_node.with_changes(body=new_body)

        return updated_node

    # -- Type annotation removal ------------------------------------------ #

    def leave_Param(
        self,
        original_node: cst.Param,
        updated_node: cst.Param,
    ) -> cst.Param:
        """
        Remove annotations from function, method, and lambda parameters.

        This also removes parameter type comments when LibCST exposes one.
        """
        del original_node

        if not self.remove_type_annotations:
            return updated_node

        if updated_node.annotation is None and updated_node.type_comment is None:
            return updated_node

        self.type_annotations_removed += 1

        return updated_node.with_changes(
            annotation=None,
            type_comment=None,
        )

    def leave_AnnAssign(
        self,
        original_node: cst.AnnAssign,
        updated_node: cst.AnnAssign,
    ) -> cst.BaseSmallStatement:
        """
        Remove variable annotations.

        ``name: int = 1`` becomes ``name = 1``.

        A bare annotation such as ``name: int`` becomes ``pass``. This keeps
        function and class suites syntactically valid without retaining the
        annotation.
        """
        del original_node

        if not self.remove_type_annotations:
            return updated_node

        self.type_annotations_removed += 1

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
        """Remove type comments attached to ordinary assignments."""
        del original_node

        if not self.remove_type_annotations:
            return updated_node

        type_comment = getattr(updated_node, "type_comment", None)
        if type_comment is None:
            return updated_node

        self.type_annotations_removed += 1
        return updated_node.with_changes(type_comment=None)

    def leave_For(
        self,
        original_node: cst.For,
        updated_node: cst.For,
    ) -> cst.For:
        """Remove type comments attached to for statements."""
        del original_node

        if not self.remove_type_annotations:
            return updated_node

        type_comment = getattr(updated_node, "type_comment", None)
        if type_comment is None:
            return updated_node

        self.type_annotations_removed += 1
        return updated_node.with_changes(type_comment=None)

    def leave_With(
        self,
        original_node: cst.With,
        updated_node: cst.With,
    ) -> cst.With:
        """Remove type comments attached to with statements."""
        del original_node

        if not self.remove_type_annotations:
            return updated_node

        type_comment = getattr(updated_node, "type_comment", None)
        if type_comment is None:
            return updated_node

        self.type_annotations_removed += 1
        return updated_node.with_changes(type_comment=None)


# --------------------------------------------------------------------------- #
# Blank-line normalization
# --------------------------------------------------------------------------- #


def _string_line_numbers(source: str) -> set[int]:
    """
    Return physical line numbers occupied by string tokens.

    Blank physical lines inside triple-quoted strings must not be removed,
    because they are part of the string value rather than source formatting.
    """
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
        # AST validation later will report invalid source. Returning an empty
        # set here avoids hiding the more useful validation error.
        return set()

    return protected


def collapse_blank_lines(source: str) -> str:
    """
    Collapse consecutive blank source lines to at most one blank line.

    Blank lines inside multiline string literals are preserved. A line that
    contains only spaces or tabs is treated as blank and normalized to the
    newline style already used by that line.
    """
    lines = source.splitlines(keepends=True)
    protected_string_lines = _string_line_numbers(source)

    result: list[str] = []
    previous_was_blank = False

    for line_number, line in enumerate(lines, start=1):
        is_blank = not line.strip()

        if is_blank and line_number not in protected_string_lines:
            if previous_was_blank:
                continue

            # Preserve the line's newline convention where possible.
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


# --------------------------------------------------------------------------- #
# Atomic file operations
# --------------------------------------------------------------------------- #


def _atomic_write(path: Path, data: bytes) -> None:
    """
    Atomically replace ``path`` with ``data``.

    The temporary file is created beside the target file, ensuring that
    ``os.replace`` remains atomic on the same filesystem.
    """
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


# --------------------------------------------------------------------------- #
# Per-file processing
# --------------------------------------------------------------------------- #


def process_file(
    path: Path,
    *,
    remove_all_comments: bool,
    remove_docstrings: bool,
    remove_type_annotations: bool,
) -> tuple[Path, int, int, int, bool, str | None]:
    """
    Transform one Python file.

    Returns:

        (
            path,
            comments_removed,
            docstrings_removed,
            type_annotations_removed,
            changed,
            error_or_none,
        )

    The input file is modified only after the generated source passes
    ``ast.parse`` validation.
    """
    try:
        source_bytes = path.read_bytes()
    except OSError as exc:
        return path, 0, 0, 0, False, f"read error: {exc}"

    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(source_bytes).readline)
        source = source_bytes.decode(encoding)
    except (SyntaxError, UnicodeDecodeError) as exc:
        return path, 0, 0, 0, False, f"encoding error: {exc}"

    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError as exc:
        return path, 0, 0, 0, False, f"LibCST parse error: {exc}"
    except Exception as exc:
        return (
            path,
            0,
            0,
            0,
            False,
            f"parse error: {type(exc).__name__}: {exc}",
        )

    transformer = SourceTransformer(
        remove_all_comments=remove_all_comments,
        remove_docstrings=remove_docstrings,
        remove_type_annotations=remove_type_annotations,
    )

    try:
        transformed_module = module.visit(transformer)
    except Exception as exc:
        return (
            path,
            0,
            0,
            0,
            False,
            f"transform error: {type(exc).__name__}: {exc}",
        )

    transformed_source = transformed_module.code

    # Always normalize repeated blank lines before validation, including when
    # blank-line cleanup is the only requested source change.
    transformed_source = collapse_blank_lines(transformed_source)

    changed = transformed_source != source

    if not changed:
        return (
            path,
            transformer.comments_removed,
            transformer.docstrings_removed,
            transformer.type_annotations_removed,
            False,
            None,
        )

    try:
        ast.parse(transformed_source, filename=str(path))
    except SyntaxError as exc:
        return (
            path,
            transformer.comments_removed,
            transformer.docstrings_removed,
            transformer.type_annotations_removed,
            False,
            f"post-transform validation failed: {exc}",
        )

    try:
        _atomic_write(path, transformed_source.encode(encoding))
    except (OSError, UnicodeEncodeError) as exc:
        return (
            path,
            transformer.comments_removed,
            transformer.docstrings_removed,
            transformer.type_annotations_removed,
            False,
            f"write error: {exc}",
        )

    return (
        path,
        transformer.comments_removed,
        transformer.docstrings_removed,
        transformer.type_annotations_removed,
        True,
        None,
    )


# --------------------------------------------------------------------------- #
# Path discovery
# --------------------------------------------------------------------------- #


def iter_python_files(roots: Iterable[Path]) -> Iterator[Path]:
    """
    Yield unique Python files under the supplied files and directories.

    Directories listed in ``SKIP_DIRS`` are pruned during recursive traversal.
    """
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


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
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
            "Remove all ordinary comments and function/class docstrings. "
            "Protected comments and the module docstring are preserved."
        ),
    )

    parser.add_argument(
        "-c",
        "--remove-all-comments",
        action="store_true",
        help=("Remove standalone comments in addition to inline comments. Protected comments are always preserved."),
    )

    parser.add_argument(
        "-d",
        "--remove-docstrings",
        action="store_true",
        help=("Remove function and class docstrings. The module docstring is preserved."),
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


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    """Run the command-line application."""
    args = build_parser().parse_args(argv)
    roots = args.paths or [Path.cwd()]

    # ``--all`` enables both ordinary standalone-comment removal and
    # function/class docstring removal.
    remove_all_comments = args.all or args.remove_all_comments
    remove_docstrings = args.all or args.remove_docstrings

    worker = functools.partial(
        process_file,
        remove_all_comments=remove_all_comments,
        remove_docstrings=remove_docstrings,
        remove_type_annotations=args.remove_type_annotations,
    )

    total_files = 0
    changed_files = 0
    total_comments = 0
    total_docstrings = 0
    total_type_annotations = 0
    error_count = 0

    with mp.Pool(processes=NUM_WORKERS) as pool:
        results = pool.imap_unordered(
            worker,
            iter_python_files(roots),
            chunksize=CHUNKSIZE,
        )

        for (
            path,
            comments_removed,
            docstrings_removed,
            type_annotations_removed,
            changed,
            error,
        ) in results:
            total_files += 1

            if error is not None:
                error_count += 1
                #                print(f"ERROR  {path.name}: {error}", file=sys.stderr)
                continue

            if not changed:
                continue

            changed_files += 1
            total_comments += comments_removed
            total_docstrings += docstrings_removed
            total_type_annotations += type_annotations_removed

            details: list[str] = []

            if comments_removed:
                details.append(f"{comments_removed} comment(s)")

            if docstrings_removed:
                details.append(f"{docstrings_removed} docstring(s)")

            if type_annotations_removed:
                details.append(f"{type_annotations_removed} type annotation(s)")

            if details:
                print(f"{path.name}: removed {', '.join(details)}")
            else:
                print(f"{path.name}: OK")

    if total_files == 0:
        print("No Python files found.", file=sys.stderr)
        return 1

    summary = (
        f"\nProcessed {total_files} file(s): "
        f"{changed_files} changed, "
        f"{total_comments} comment(s), "
        f"{total_docstrings} docstring(s), "
        f"{total_type_annotations} type annotation(s) removed, "
        f"{error_count} error(s)."
    )

    print(summary, file=sys.stderr if error_count else sys.stdout)

    return 2 if error_count else 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
