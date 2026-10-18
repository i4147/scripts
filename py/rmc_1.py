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
    tw = getattr(node, "trailing_whitespace", None)
    return tw is not None and getattr(tw, "comment", None) is not None


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
    remaining_small = list(first.body[1:])
    rest = list(block.body[1:])
    if remaining_small:
        new_first = first.with_changes(body=remaining_small)
        return block.with_changes(body=[new_first, *rest]), True
    if not rest or _has_trailing_comment(first):
        new_first = first.with_changes(body=[cst.Pass()])
        return block.with_changes(body=[new_first, *rest]), True
    if first.leading_lines:
        next_stmt = rest[0]
        existing = list(getattr(next_stmt, "leading_lines", ()) or ())
        merged = list(first.leading_lines) + existing
        try:
            rest[0] = next_stmt.with_changes(leading_lines=merged)
        except AttributeError:
            pass
    return block.with_changes(body=rest), True


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


class CommentAndDocstringRemover(cst.CSTTransformer):
    def __init__(
        self,
        *,
        remove_all_comments: bool,
        remove_docstrings: bool,
    ) -> None:
        super().__init__()
        self._remove_all_comments = remove_all_comments
        self._remove_docstrings = remove_docstrings
        self.comments_removed: int = 0
        self.docstrings_removed: int = 0

    @staticmethod
    def _is_protected(comment_text: str) -> bool:
        return comment_text.startswith(PROTECTED_COMMENT_PREFIXES)

    def leave_TrailingWhitespace(
        self,
        original_node: cst.TrailingWhitespace,
        updated_node: cst.TrailingWhitespace,
    ) -> cst.TrailingWhitespace:
        if updated_node.comment is None:
            return updated_node
        if self._is_protected(updated_node.comment.value):
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
        if not self._remove_all_comments:
            return updated_node
        if updated_node.comment is None:
            return updated_node
        if self._is_protected(updated_node.comment.value):
            return updated_node
        self.comments_removed += 1
        return updated_node.with_changes(comment=None)

    def leave_FunctionDef(
        self,
        original_node: cst.FunctionDef,
        updated_node: cst.FunctionDef,
    ) -> cst.FunctionDef:
        if not self._remove_docstrings:
            return updated_node
        new_body, removed = _strip_docstring(updated_node.body)
        if removed:
            self.docstrings_removed += 1
            return updated_node.with_changes(body=new_body)
        return updated_node

    def leave_ClassDef(
        self,
        original_node: cst.ClassDef,
        updated_node: cst.ClassDef,
    ) -> cst.ClassDef:
        if not self._remove_docstrings:
            return updated_node
        new_body, removed = _strip_docstring(updated_node.body)
        if removed:
            self.docstrings_removed += 1
            return updated_node.with_changes(body=new_body)
        return updated_node


def _atomic_write(path: Path, data: bytes) -> None:
    try:
        mode: int | None = path.stat().st_mode
    except OSError:
        mode = None
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        if mode is not None:
            try:
                os.chmod(tmp_path, mode)
            except OSError:
                pass
        os.replace(tmp_path, path)
    except BaseException:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def process_file(
    path: Path,
    *,
    remove_all_comments: bool,
    remove_docstrings: bool,
) -> tuple[Path, int, int, str | None]:
    try:
        source_bytes = path.read_bytes()
    except OSError as exc:
        return path, 0, 0, f"read error: {exc}"
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(source_bytes).readline)
        source = source_bytes.decode(encoding)
    except (SyntaxError, UnicodeDecodeError) as exc:
        return path, 0, 0, f"encoding error: {exc}"
    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError as exc:
        return path, 0, 0, f"libcst parse error: {exc}"
    except Exception as exc:
        return path, 0, 0, f"parse error: {type(exc).__name__}: {exc}"
    transformer = CommentAndDocstringRemover(
        remove_all_comments=remove_all_comments,
        remove_docstrings=remove_docstrings,
    )
    try:
        new_module = module.visit(transformer)
    except Exception as exc:
        return path, 0, 0, f"transform error: {type(exc).__name__}: {exc}"
    if transformer.comments_removed == 0 and transformer.docstrings_removed == 0:
        return path, 0, 0, None
    new_source = new_module.code
    try:
        ast.parse(new_source, filename=str(path))
    except SyntaxError as exc:
        return path, 0, 0, f"post-transform validation failed: {exc}"
    try:
        _atomic_write(path, new_source.encode(encoding))
    except (OSError, UnicodeEncodeError) as exc:
        return path, 0, 0, f"write error: {exc}"
    return path, transformer.comments_removed, transformer.docstrings_removed, None


def iter_python_files(roots: Iterable[Path]) -> Iterator[Path]:
    seen: set[Path] = set()

    def _on_error(exc: OSError) -> None:
        print(f"warning: {exc}", file=sys.stderr)

    for root in roots:
        try:
            if root.is_file():
                if root.suffix in PYTHON_SUFFIXES:
                    key = root.resolve()
                    if key not in seen:
                        seen.add(key)
                        yield root
            elif root.is_dir():
                for dirpath, dirnames, filenames in root.walk(on_error=_on_error):
                    dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
                    for name in filenames:
                        if not name.endswith(PYTHON_SUFFIXES):
                            continue
                        candidate = dirpath / name
                        try:
                            key = candidate.resolve()
                        except OSError:
                            continue
                        if key in seen:
                            continue
                        seen.add(key)
                        yield candidate
            else:
                print(f"warning: skipping non-existent path: {root}", file=sys.stderr)
        except OSError as exc:
            print(f"warning: cannot access {root}: {exc}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="strip_comments",
        description=(
            "Remove inline comments (default), all comments (-c), and/or "
            "docstrings (-d) from Python files using libcst. Files are "
            "modified in place. Shebangs and tool directives are preserved."
        ),
    )
    parser.add_argument(
        "-c",
        "--remove-all-comments",
        action="store_true",
        help=(
            "Also remove standalone comments, not just inline ones. "
            "Shebangs and tool directives (# fmt, # type, # noqa, ...) are "
            "always preserved."
        ),
    )
    parser.add_argument(
        "-d",
        "--remove-docstrings",
        action="store_true",
        help=(
            "Remove docstrings from function and class bodies. The module "
            "docstring is preserved. A docstring-only body is replaced "
            "with 'pass'."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        metavar="PATH",
        help=("Files or directories to process. Defaults to the current directory, walked recursively."),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    roots: list[Path] = args.paths or [Path.cwd()]
    worker = functools.partial(
        process_file,
        remove_all_comments=args.remove_all_comments,
        remove_docstrings=args.remove_docstrings,
    )
    total_files = 0
    changed_files = 0
    total_comments = 0
    total_docstrings = 0
    error_count = 0
    with mp.Pool(processes=NUM_WORKERS) as pool:
        results = pool.imap_unordered(
            worker,
            iter_python_files(roots),
            chunksize=CHUNKSIZE,
        )
        for path, comments, docstrings, error in results:
            total_files += 1
            if error is not None:
                error_count += 1
                print(f"ERROR  {path}: {error}", file=sys.stderr)
                continue
            if comments == 0 and docstrings == 0:
                continue
            changed_files += 1
            total_comments += comments
            total_docstrings += docstrings
            bits: list[str] = []
            if comments:
                bits.append(f"{comments} comment(s)")
            if docstrings:
                bits.append(f"{docstrings} docstring(s)")
            print(f"{path}: removed {', '.join(bits)}")
    if total_files == 0:
        print("No Python files found.", file=sys.stderr)
        return 1
    summary = (
        f"\nProcessed {total_files} file(s): "
        f"{changed_files} changed, "
        f"{total_comments} comment(s) and "
        f"{total_docstrings} docstring(s) removed, "
        f"{error_count} error(s)."
    )
    print(summary, file=sys.stderr if error_count else sys.stdout)
    return 2 if error_count else 0


if __name__ == "__main__":
    sys.exit(main())
