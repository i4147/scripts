from __future__ import annotations

import argparse
import ast
import io
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import libcst as cst
import libcst.matchers as m


def find_module_docstring(source: str) -> tuple[int, int] | None:
    try:
        module = ast.parse(source)
    except SyntaxError:
        return None
    doc = ast.get_docstring(module)
    if doc is None:
        return None
    if not module.body:
        return None
    first_stmt = module.body[0]
    if not isinstance(first_stmt, ast.Expr) or not isinstance(getattr(first_stmt, "value", None), ast.Constant):
        return None
    value = first_stmt.value
    if not isinstance(value.value, str):
        return None
    start_line = getattr(value, "lineno", None)
    end_line = getattr(value, "end_lineno", None)
    if start_line is None or end_line is None:
        return None
    return start_line, end_line


class StripCommentsAndDocstrings(cst.CSTTransformer):
    def __init__(self, module_doc_range: tuple[int, int] | None):
        super().__init__()
        self.module_doc_range = module_doc_range
        self.comments_removed = 0
        self.docstrings_removed = 0

    def leave_TrailingWhitespace(
        self,
        original_node: cst.TrailingWhitespace,
        updated_node: cst.TrailingWhitespace,
    ) -> cst.TrailingWhitespace:
        if updated_node.comment is not None:
            self.comments_removed += 1
            updated_node = updated_node.with_changes(comment=None)
        return updated_node

    def leave_EmptyLine(self, original_node: cst.EmptyLine, updated_node: cst.EmptyLine) -> cst.EmptyLine:
        if updated_node.comment is not None:
            self.comments_removed += 1
            updated_node = updated_node.with_changes(comment=None)
        return updated_node

    def _is_docstring_expr(self, node: cst.CSTNode) -> bool:
        if not isinstance(node, cst.SimpleStatementLine):
            return False
        if len(node.body) != 1:
            return False
        expr = node.body[0]
        if not isinstance(expr, cst.Expr):
            return False
        value = expr.value
        return m.matches(
            value,
            m.OneOf(
                m.SimpleString(),
                m.ConcatenatedString(),
            ),
        )

    def leave_SimpleStatementLine(
        self,
        original_node: cst.SimpleStatementLine,
        updated_node: cst.SimpleStatementLine,
    ) -> cst.CSTNode | None:
        if not self._is_docstring_expr(updated_node):
            return updated_node
        self.docstrings_removed += 1
        return cst.RemovalSentinel


def process_file(path: Path) -> tuple[Path, int, int, bool, str | None]:
    text = path.read_text(encoding="utf-8")
    shebang = ""
    remainder = text
    if text.startswith("#!"):
        buf = io.StringIO(text)
        first_line = buf.readline()
        shebang = first_line
        remainder = buf.read()
    module_doc_range = find_module_docstring(remainder)
    module = cst.parse_module(remainder)
    transformer = StripCommentsAndDocstrings(module_doc_range)
    modified = module.visit(transformer)
    new_code = modified.code
    if shebang:
        new_code = shebang + new_code.lstrip("\n")
    try:
        ast.parse(new_code)
    except SyntaxError as e:
        return (
            path,
            transformer.comments_removed,
            transformer.docstrings_removed,
            False,
            str(e),
        )
    path.write_text(new_code, encoding="utf-8")
    return (
        path,
        transformer.comments_removed,
        transformer.docstrings_removed,
        True,
        None,
    )


def iter_python_files_from_paths(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    for p in paths:
        if p.is_file() and p.suffix == ".py":
            result.append(p)
        elif p.is_dir():
            result.extend(q for q in p.rglob("*.py") if q.is_file())
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strip comments and non-module docstrings from Python files.")
    parser.add_argument(
        "paths",
        type=Path,
        nargs="*",
        help=("Files and/or directories to process. If omitted, '.' is used and searched recursively."),
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=0,
        help=("Number of worker processes (default: CPU count). Use 1 to disable parallelism."),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_paths: list[Path] = args.paths or [Path(".")]
    files = iter_python_files_from_paths(input_paths)
    if not files:
        print("No Python files found to process.")
        return
    jobs = args.jobs or None
    if jobs == 1:
        for path in files:
            file_path, comments_removed, docstrings_removed, written, error = process_file(path)
            if written:
                print(f"{file_path}: removed {comments_removed} comments, {docstrings_removed} docstrings")
            else:
                print(
                    f"{file_path}: INVALID after transform, "
                    f"skipped write (removed {comments_removed} comments, "
                    f"{docstrings_removed} docstrings). Error: {error}"
                )
    else:
        with ProcessPoolExecutor(max_workers=jobs) as executor:
            futures = {executor.submit(process_file, path): path for path in files}
            for fut in as_completed(futures):
                file_path, comments_removed, docstrings_removed, written, error = fut.result()
                if written:
                    print(f"{file_path}: removed {comments_removed} comments, {docstrings_removed} docstrings")
                else:
                    print(
                        f"{file_path}: INVALID after transform, "
                        f"skipped write (removed {comments_removed} comments, "
                        f"{docstrings_removed} docstrings). Error: {error}"
                    )


if __name__ == "__main__":
    raise SystemExit(main())
