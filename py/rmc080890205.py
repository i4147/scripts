from __future__ import annotations

import argparse
import ast
import io
import sys
import tokenize
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


SKIP_DIRS = {".git", "__pycache__"}

PRESERVE_COMMENT_PREFIXES = (
    "#!",
    "# fmt",
    "# type",
    "# noqa",
)


def _is_docstring_node(node: ast.AST) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


def _should_preserve_comment(text: str) -> bool:
    stripped = text.strip()
    if stripped.startswith("#!"):
        return True
    for prefix in PRESERVE_COMMENT_PREFIXES:
        if stripped.lower().startswith(prefix.lower()):
            return True
    return False


class _DocstringInfo:
    def __init__(self, source: str, tree: ast.Module, remove_module_doc: bool):
        self.source = source
        self.remove_module_doc = remove_module_doc
        self.to_remove: set[tuple[int, int]] = set()
        self.needs_pass: set[tuple[int, int]] = set()
        self._collect(tree)

    def _collect(self, tree: ast.Module) -> None:
        if self.remove_module_doc and tree.body and _is_docstring_node(tree.body[0]):
            node = tree.body[0]
            self.to_remove.add((node.lineno, node.col_offset))

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if not node.body:
                continue
            first = node.body[0]
            if not _is_docstring_node(first):
                continue
            key = (first.lineno, first.col_offset)
            self.to_remove.add(key)
            if len(node.body) == 1:
                self.needs_pass.add(key)


def _collect_comment_ranges(
    source: str,
) -> list[tuple[int, int, int, int, bool]]:
    results = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            if tok.type != tokenize.COMMENT:
                continue
            sr, sc = tok.start
            er, ec = tok.end
            preserve = _should_preserve_comment(tok.string)
            results.append((sr, sc, er, ec, preserve))
    except tokenize.TokenError:
        pass
    return results


def _lines_to_offsets(source: str) -> list[int]:
    offsets = [0]
    pos = 0
    for ch in source:
        pos += 1
        if ch == "\n":
            offsets.append(pos)
    return offsets


def _rowcol_to_offset(offsets: list[int], row: int, col: int) -> int:
    return offsets[row] + col


def process_source(source: str, remove_module_doc: bool) -> tuple[str, int, int]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ValueError(f"Source has syntax error: {exc}") from exc

    offsets = _lines_to_offsets(source)

    doc_info = _DocstringInfo(source, tree, remove_module_doc)

    expr_nodes: dict[tuple[int, int], ast.Expr] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr):
            expr_nodes[(node.lineno, node.col_offset)] = node

    doc_removals: list[tuple[int, int, str]] = []
    n_doc = 0

    for key in doc_info.to_remove:
        expr_node = expr_nodes.get(key)
        if expr_node is None:
            continue
        if not hasattr(expr_node, "end_lineno"):
            continue

        start = _rowcol_to_offset(offsets, expr_node.lineno, expr_node.col_offset)
        end = _rowcol_to_offset(offsets, expr_node.end_lineno, expr_node.end_col_offset)

        while end < len(source) and source[end] in ("\n", "\r"):
            end += 1

        replacement = ""
        if key in doc_info.needs_pass:
            indent = " " * expr_node.col_offset
            replacement = f"{indent}pass\n"

        doc_removals.append((start, end, replacement))
        n_doc += 1

    comment_tokens = _collect_comment_ranges(source)
    comment_removals: list[tuple[int, int, str]] = []
    n_comments = 0

    for sr, sc, er, ec, preserve in comment_tokens:
        if preserve:
            continue
        start = _rowcol_to_offset(offsets, sr, sc)
        end = _rowcol_to_offset(offsets, er, ec)

        line_start = offsets[sr]
        before_comment = source[line_start:start]
        is_whole_line = before_comment.strip() == ""

        if is_whole_line:
            start = line_start
            if end < len(source) and source[end] == "\n":
                end += 1

        comment_removals.append((start, end, ""))
        n_comments += 1

    all_removals = sorted(doc_removals + comment_removals, key=lambda x: x[0])

    merged: list[tuple[int, int, str]] = []
    last_end = -1
    for start, end, repl in all_removals:
        if start < last_end:
            continue
        merged.append((start, end, repl))
        last_end = end

    if not merged:
        return source, 0, 0

    parts: list[str] = []
    cursor = 0
    for start, end, repl in merged:
        parts.append(source[cursor:start])
        parts.append(repl)
        cursor = end
    parts.append(source[cursor:])

    new_source = "".join(parts)

    try:
        ast.parse(new_source)
    except SyntaxError as exc:
        raise ValueError(f"Result failed ast.parse validation: {exc}") from exc

    return new_source, n_comments, n_doc


def process_file(path_str: str, remove_module_doc: bool) -> dict:
    path = Path(path_str)
    result = {
        "path": path_str,
        "comments": 0,
        "docstrings": 0,
        "skipped": False,
        "skip_reason": "",
        "error": "",
    }
    try:
        source = path.read_text(encoding="utf-8")
    except Exception as exc:
        result["error"] = f"read error: {exc}"
        return result

    try:
        new_source, n_comments, n_doc = process_source(source, remove_module_doc)
    except ValueError as exc:
        result["error"] = str(exc)
        return result

    total = n_comments + n_doc
    if total == 0:
        result["skipped"] = True
        result["skip_reason"] = "nothing to remove"
        return result

    try:
        path.write_text(new_source, encoding="utf-8")
    except Exception as exc:
        result["error"] = f"write error: {exc}"
        return result

    result["comments"] = n_comments
    result["docstrings"] = n_doc
    return result


def walk_python_files(root: Path):
    if root.is_symlink():
        return
    if root.is_file():
        if root.suffix == ".py":
            yield root
        return
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except PermissionError:
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name not in SKIP_DIRS:
                    stack.append(entry)
            elif entry.is_file() and entry.suffix == ".py":
                yield entry


def collect_targets(inputs: list[str]) -> list[Path]:
    if not inputs:
        return [Path(".")]
    return [Path(p).expanduser().resolve() for p in inputs]


RESET = "\033[0m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
BOLD = "\033[1m"


def _fmt(color: str, text: str) -> str:
    return f"{color}{text}{RESET}" if sys.stdout.isatty() else text


def report_result(res: dict) -> None:
    path = res["path"]
    if res["error"]:
        print(f"  {_fmt(RED, 'ERROR')} {path}: {res['error']}")
    elif res["skipped"]:
        pass
    else:
        c = res["comments"]
        d = res["docstrings"]
        parts = []
        if c:
            parts.append(f"{c} comment{'s' if c != 1 else ''}")
        if d:
            parts.append(f"{d} docstring{'s' if d != 1 else ''}")
        print(f"  {_fmt(GREEN, 'cleaned')} {path}: removed {', '.join(parts)}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rmc",
        description="Remove comments and docstrings from Python files.",
    )
    p.add_argument(
        "targets",
        nargs="*",
        metavar="PATH",
        help="Files or directories to process (default: current directory).",
    )
    p.add_argument(
        "-r",
        "--remove-module-docstrings",
        action="store_true",
        default=False,
        help="Also remove module-level docstrings (preserved by default).",
    )
    p.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=None,
        metavar="N",
        help="Number of parallel worker processes (default: cpu count).",
    )
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    targets = collect_targets(args.targets)
    remove_module_doc: bool = args.remove_module_docstrings

    all_files: list[Path] = []
    for target in targets:
        if not target.exists():
            print(f"{_fmt(RED, 'warning')}: path not found: {target}", file=sys.stderr)
            continue
        for f in walk_python_files(target):
            all_files.append(f)

    seen: set[Path] = set()
    unique_files: list[Path] = []
    for f in all_files:
        resolved = f.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique_files.append(f)

    if not unique_files:
        print("No Python files found.")
        return 0

    print(
        f"{_fmt(BOLD, 'rmc')} — processing "
        f"{_fmt(CYAN, str(len(unique_files)))} file(s)" + (" [removing module docstrings]" if remove_module_doc else "")
    )

    total_comments = 0
    total_docstrings = 0
    total_errors = 0
    total_cleaned = 0

    with ProcessPoolExecutor(max_workers=args.jobs) as executor:
        futures = {executor.submit(process_file, str(f), remove_module_doc): f for f in unique_files}
        for future in as_completed(futures):
            try:
                res = future.result()
            except Exception as exc:
                path = str(futures[future])
                print(f"  {_fmt(RED, 'ERROR')} {path}: unexpected: {exc}")
                total_errors += 1
                continue

            report_result(res)
            if res["error"]:
                total_errors += 1
            elif not res["skipped"]:
                total_cleaned += 1
                total_comments += res["comments"]
                total_docstrings += res["docstrings"]

    print(
        f"\n{_fmt(BOLD, 'done')} — "
        f"{total_cleaned} file(s) cleaned, "
        f"{total_comments} comment(s) removed, "
        f"{total_docstrings} docstring(s) removed"
        + (f", {_fmt(RED, str(total_errors) + ' error(s)')}" if total_errors else "")
    )
    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
