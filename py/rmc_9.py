"""
strip_comments.py

Safely remove comments, docstrings, type annotations, and repeated blank lines
from Python source files using LibCST.

Output mode (when run with --stats):
    Prints filename and bytes reduced (original size - new size) in green.
    Example:
        a.py    123 B
        b.py   1056 B
"""

import argparse
import ast
import io
import multiprocessing as mp
import os
import sys
import tempfile
import tokenize as az
from pathlib import Path
from functools import partial

import libcst as cst

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

MAX_WORKERS = 8
CHUNKSIZE = 4

PYTHON_SUFFIXES = (".py", ".pyi")

SKIP_DIRS = frozenset(
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

PROTECTED_COMMENT_PREFIXES = (
    "#!",
    "#-*-",
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

# ---------------------------------------------------------------------------
# Docstring detection helpers
# ---------------------------------------------------------------------------


def is_docstring_literal(node: cst.CSTNode) -> bool:
    """Return whether a CST expression is a valid Python docstring literal.

    Bytes literals and f-strings are not considered docstrings. Concatenated
    string literals are docstrings only when both sides are ordinary strings.
    """
    if isinstance(node, cst.SimpleString):
        return "b" not in node.prefix.lower()
    if isinstance(node, cst.ConcatenatedString):
        return is_docstring_literal(node.left) and is_docstring_literal(node.right)
    return False


def statement_starts_with_docstring(statement: cst.SimpleStatementLine) -> bool:
    """Return whether a statement line begins with a docstring expression."""
    if not statement.body:
        return False
    first = statement.body[0]
    return isinstance(first, cst.Expr) and is_docstring_literal(first.value)


def has_trailing_comment(node: cst.CSTNode) -> bool:
    """Return whether a CST node has a trailing comment."""
    trailing = getattr(node, "trailing_whitespace", None)
    return trailing is not None and getattr(trailing, "comment", None) is not None


# ---------------------------------------------------------------------------
# Docstring removal for suites
# ---------------------------------------------------------------------------


def remove_docstring_from_indented_block(
    block: cst.IndentedBlock,
) -> tuple[cst.IndentedBlock, bool]:
    """Remove the first docstring from an indented suite.

    A ``pass`` statement is inserted when removing the docstring would leave
    an invalid empty function or class body.
    """
    if not block.body:
        return block, False

    first = block.body[0]
    if not isinstance(first, cst.SimpleStatementLine):
        return block, False
    if not statement_starts_with_docstring(first):
        return block, False

    remaining_in_line = list(first.body[1:])
    remaining_in_block = list(block.body[1:])

    # Case 1: the docstring line also contains other statements.
    if remaining_in_line:
        new_first = first.with_changes(body=remaining_in_line)
        return block.with_changes(body=[new_first, *remaining_in_block]), True

    # Case 2: nothing left after the docstring, or the line has a trailing comment.
    if not remaining_in_block or has_trailing_comment(first):
        new_first = first.with_changes(body=[cst.Pass()])
        return block.with_changes(body=[new_first, *remaining_in_block]), True

    # Case 3: drop the docstring line entirely, moving its leading lines
    #         to the next statement.
    if first.leading_lines:
        next_stmt = remaining_in_block[0]
        next_leading = list(getattr(next_stmt, "leading_lines", ()) or ())
        merged = [*first.leading_lines, *next_leading]
        try:
            remaining_in_block[0] = next_stmt.with_changes(leading_lines=merged)
        except AttributeError:
            pass

    return block.with_changes(body=remaining_in_block), True


def remove_docstring_from_simple_suite(
    suite: cst.SimpleStatementSuite,
) -> tuple[cst.SimpleStatementSuite, bool]:
    """Remove the first docstring from a one-line suite.

    For example::

        def function(): "doc"

    becomes::

        def function(): pass
    """
    if not suite.body:
        return suite, False

    first = suite.body[0]
    if not (isinstance(first, cst.Expr) and is_docstring_literal(first.value)):
        return suite, False

    remaining = list(suite.body[1:])
    if not remaining:
        remaining = [cst.Pass()]

    return suite.with_changes(body=remaining), True


def remove_leading_docstring(
    body: cst.BaseSuite,
) -> tuple[cst.BaseSuite, bool]:
    """Remove a leading docstring from an arbitrary CST suite."""
    if isinstance(body, cst.IndentedBlock):
        return remove_docstring_from_indented_block(body)
    if isinstance(body, cst.SimpleStatementSuite):
        return remove_docstring_from_simple_suite(body)
    return body, False


# ---------------------------------------------------------------------------
# LibCST transformer
# ---------------------------------------------------------------------------


class DocstringAndCommentRemover(cst.CSTTransformer):
    """Remove selected source constructs from a LibCST tree.

    The module docstring is preserved because only FunctionDef and ClassDef
    bodies are passed through the docstring remover. Inline comments are
    removed by default. Standalone comments are removed only when
    ``remove_all_comments`` is enabled. Protected comments are always
    preserved.
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

    # -- Comments ----------------------------------------------------------

    def leave_TrailingWhitespace(
        self,
        original_node: cst.TrailingWhitespace,
        updated_node: cst.TrailingWhitespace,
    ) -> cst.TrailingWhitespace:
        """Remove ordinary inline comments."""
        del original_node
        if updated_node.comment is None:
            return updated_node

        comment_value = updated_node.comment.value
        if self._is_protected_comment(comment_value):
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

        comment_value = updated_node.comment.value
        if self._is_protected_comment(comment_value):
            return updated_node

        self.comments_removed += 1
        return updated_node.with_changes(comment=None)

    # -- Docstrings --------------------------------------------------------

    def leave_FunctionDef(
        self,
        original_node: cst.FunctionDef,
        updated_node: cst.FunctionDef,
    ) -> cst.FunctionDef:
        """Remove function docstrings and return annotations.

        Parameter annotations are removed separately by ``leave_Param``.
        """
        del original_node

        if self.remove_docstrings:
            new_body, removed = remove_leading_docstring(updated_node.body)
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

        new_body, removed = remove_leading_docstring(updated_node.body)
        if removed:
            self.docstrings_removed += 1
            return updated_node.with_changes(body=new_body)
        return updated_node

    # -- Type annotations --------------------------------------------------

    def leave_Param(
        self,
        original_node: cst.Param,
        updated_node: cst.Param,
    ) -> cst.Param:
        """Remove annotations from function, method, and lambda parameters.

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
    ) -> cst.BaseStatement:
        """Remove variable annotations.

        ``name: int = 1`` becomes ``name = 1``. A bare annotation such as
        ``name: int`` becomes ``pass``. This keeps function and class suites
        syntactically valid without retaining the annotation.
        """
        del original_node
        if not self.remove_type_annotations:
            return updated_node

        self.type_annotations_removed += 1
        if updated_node.value is None:
            return cst.Pass()

        return cst.Assign(
            targets=[cst.AssignTarget(target=updated_node.target)],
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


# ---------------------------------------------------------------------------
# Blank-line collapsing
# ---------------------------------------------------------------------------


def collect_string_line_numbers(source: str) -> set[int]:
    """Return physical line numbers occupied by string tokens.

    Blank physical lines inside triple-quoted strings must not be removed,
    because they are part of the string value rather than source formatting.
    """
    line_numbers: set[int] = set()
    try:
        tokens = az.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type != az.STRING:
                continue
            start_line = token.start[0]
            end_line = token.end[0]
            line_numbers.update(range(start_line, end_line + 1))
    except (IndentationError, az.TokenError):
        return set()
    return line_numbers


def collapse_blank_lines(source: str) -> str:
    """Collapse consecutive blank source lines to at most one blank line.

    Blank lines inside multiline string literals are preserved. A line that
    contains only spaces or tabs is treated as blank and normalized to the
    newline style already used by that line.
    """
    lines = source.splitlines(keepends=True)
    string_lines = collect_string_line_numbers(source)
    result: list[str] = []
    previous_was_blank = False

    for line_number, line in enumerate(lines, start=1):
        is_blank = not line.strip()
        if is_blank and line_number not in string_lines:
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


# ---------------------------------------------------------------------------
# Atomic file writing
# ---------------------------------------------------------------------------


def atomic_replace(path: Path, data: bytes) -> None:
    """Atomically replace ``path`` with ``data``.

    The temporary file is created beside the target file, ensuring that
    ``os.replace`` remains atomic on the same filesystem.
    """
    try:
        original_mode = path.stat().st_mode
    except OSError:
        original_mode = None

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temp_path = Path(temp_name)

    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

        if original_mode is not None:
            try:
                os.chmod(temp_path, original_mode)
            except OSError:
                pass

        os.replace(temp_path, path)
    except BaseException:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Per-file transformation
# ---------------------------------------------------------------------------


def transform_file(
    path: Path,
    *,
    remove_all_comments: bool,
    remove_docstrings: bool,
    remove_type_annotations: bool,
) -> tuple[Path, int, int, int, bool, int, str | None]:
    """Transform one Python file.

    Returns:
        path,
        comments_removed,
        docstrings_removed,
        type_annotations_removed,
        changed,
        bytes_saved,
        error_or_none,
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return path, 0, 0, 0, False, 0, f"read error: {exc}"

    try:
        encoding, _ = az.detect_encoding(io.BytesIO(raw).readline)
        source = raw.decode(encoding)
    except (SyntaxError, UnicodeDecodeError) as exc:
        return path, 0, 0, 0, False, 0, f"encoding error: {exc}"

    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError as exc:
        return path, 0, 0, 0, False, 0, f"LibCST parse error: {exc}"
    except Exception as exc:
        return path, 0, 0, 0, False, 0, f"parse error: {type(exc).__name__}: {exc}"

    transformer = DocstringAndCommentRemover(
        remove_all_comments=remove_all_comments,
        remove_docstrings=remove_docstrings,
        remove_type_annotations=remove_type_annotations,
    )

    try:
        new_module = module.visit(transformer)
    except Exception as exc:
        return path, 0, 0, 0, False, 0, f"transform error: {type(exc).__name__}: {exc}"

    new_source = new_module.code
    new_source = collapse_blank_lines(new_source)
    changed = new_source != source

    if not changed:
        return (
            path,
            transformer.comments_removed,
            transformer.docstrings_removed,
            transformer.type_annotations_removed,
            False,
            0,
            None,
        )

    try:
        ast.parse(new_source, filename=str(path))
    except SyntaxError as exc:
        return (
            path,
            transformer.comments_removed,
            transformer.docstrings_removed,
            transformer.type_annotations_removed,
            False,
            0,
            f"post-transform validation failed: {exc}",
        )

    encoded = new_source.encode(encoding)
    bytes_saved = len(raw) - len(encoded)

    try:
        atomic_replace(path, encoded)
    except (OSError, UnicodeEncodeError) as exc:
        return (
            path,
            transformer.comments_removed,
            transformer.docstrings_removed,
            transformer.type_annotations_removed,
            False,
            0,
            f"write error: {exc}",
        )

    return (
        path,
        transformer.comments_removed,
        transformer.docstrings_removed,
        transformer.type_annotations_removed,
        True,
        bytes_saved,
        None,
    )


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def discover_python_files(paths: list[Path]):
    """Yield unique Python files under the supplied files and directories.

    Directories listed in ``SKIP_DIRS`` are pruned during recursive traversal.
    """
    seen: set[Path] = set()

    def warn(message: str) -> None:
        print(f"warning: {message}", file=sys.stderr)

    for path in paths:
        try:
            if path.is_file():
                if path.suffix in PYTHON_SUFFIXES:
                    resolved = path.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        yield path
            elif path.is_dir():
                for root, dirs, files in path.walk(on_error=warn):
                    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                    for name in files:
                        if not name.endswith(PYTHON_SUFFIXES):
                            continue
                        candidate = root / name
                        try:
                            resolved = candidate.resolve()
                        except OSError:
                            continue
                        if resolved in seen:
                            continue
                        seen.add(resolved)
                        yield candidate
            else:
                print(f"warning: skipping non-existent path: {path}", file=sys.stderr)
        except OSError as exc:
            print(f"warning: cannot access {path}: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Command-line interface
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="strip_comments",
        description=(
            "Safely remove comments, docstrings, type annotations, and repeated "
            "blank lines from Python files using LibCST."
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
        help="Remove function and class docstrings. The module docstring is preserved.",
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
        help="Python files or directories to process. Defaults to the current directory.",
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    """Run the command-line application."""
    args = build_parser().parse_args(argv)
    paths = args.paths or [Path.cwd()]

    remove_all_comments = args.all or args.remove_all_comments
    remove_docstrings = args.all or args.remove_docstrings

    worker = partial(
        transform_file,
        remove_all_comments=remove_all_comments,
        remove_docstrings=remove_docstrings,
        remove_type_annotations=args.remove_type_annotations,
    )

    processed = 0
    changed = 0
    comments_removed = 0
    docstrings_removed = 0
    type_annotations_removed = 0
    errors = 0

    with mp.Pool(processes=MAX_WORKERS) as pool:
        results = pool.imap_unordered(
            worker,
            discover_python_files(paths),
            chunksize=CHUNKSIZE,
        )

        for (
            path,
            comments,
            docstrings,
            annotations,
            was_changed,
            bytes_saved,
            error,
        ) in results:
            processed += 1

            if error is not None:
                errors += 1
                print(f"{path}: {error}", file=sys.stderr)
                continue

            if not was_changed:
                continue

            changed += 1
            comments_removed += comments
            docstrings_removed += docstrings
            type_annotations_removed += annotations

            # Requested output format: filename + bytes reduced, number in green.
            print(f"{path.name}    {GREEN}{bytes_saved} B{RESET}")

    if processed == 0:
        print("No Python files found.", file=sys.stderr)
        return 1

    summary = (
        f"\nProcessed {processed} file(s): "
        f"{changed} changed, "
        f"{comments_removed} comment(s), "
        f"{docstrings_removed} docstring(s), "
        f"{type_annotations_removed} type annotation(s) removed, "
        f"{errors} error(s)."
    )
    print(summary, file=sys.stderr if errors else sys.stdout)
    return 2 if errors else 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(run())
