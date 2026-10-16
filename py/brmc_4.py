from __future__ import annotations

import argparse
import ast
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from dh import get_pyfiles


def _first_statement_is_docstring(tree: ast.Module) -> bool:
    if not tree.body:
        return False
    node = tree.body[0]
    return (
        isinstance(node, ast.Expr)
        and isinstance(getattr(node, "value", None), ast.Constant)
        and isinstance(node.value.value, str)
    )


def _remove_docstrings_from_source(source: str) -> tuple[str, int]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source, 0
    to_remove: list[tuple[int, int, int, int]] = []
    preserve_module = _first_statement_is_docstring(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr):
            continue
        val = getattr(node, "value", None)
        if not isinstance(val, ast.Constant) or not isinstance(val.value, str):
            continue
        if preserve_module and tree.body and node is tree.body[0]:
            continue
        if hasattr(node, "lineno") and hasattr(node, "end_lineno"):
            to_remove.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset))
    if not to_remove:
        return source, 0
    lines = source.splitlines(keepends=True)
    to_remove.sort(key=lambda r: (r[0], r[1]), reverse=True)
    for sline, scol, eline, ecol in to_remove:
        sidx = sline - 1
        eidx = eline - 1
        if sidx < 0 or eidx >= len(lines):
            continue
        if sidx == eidx:
            line = lines[sidx]
            lines[sidx] = line[:scol] + "" + line[ecol:]
        else:
            first = lines[sidx]
            last = lines[eidx]
            lines[sidx] = first[:scol]
            lines[eidx] = last[ecol:]
            for mid in range(sidx + 1, eidx):
                lines[mid] = ""
    new_source = "".join(lines)
    return new_source, len(to_remove)


def _validate_syntax(source: str) -> bool:
    try:
        ast.parse(source)
        return True
    except SyntaxError:
        return False


def _split_code_and_comment(line: str) -> tuple[str, str | None]:
    in_squote = False
    in_dquote = False
    escaped = False
    for i, ch in enumerate(line):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if in_squote:
            if ch == "'":
                in_squote = False
            continue
        if in_dquote:
            if ch == '"':
                in_dquote = False
            continue
        if ch == "'":
            in_squote = True
            continue
        if ch == '"':
            in_dquote = True
            continue
        if ch == "#":
            return line[:i], line[i:]
    return line, None


def _should_preserve_comment(comment: str, *, is_line_start: bool) -> bool:
    s = comment.strip()
    if is_line_start and s.startswith("#!"):
        return True
    if is_line_start and ("coding" in s) and s.startswith("#"):
        lower = s.lower()
        if lower.startswith("# coding:") or "coding:" in lower:
            return True
    if s.startswith("# type:"):
        return True
    if s.startswith(("# fmt", "#fmt")):
        return True
    return bool(s.startswith(("# noqa", "# nosec", "# lint")))


def _remove_comments_from_source(source: str) -> tuple[str, int]:
    out_lines: list[str] = []
    removed = 0
    lines = source.splitlines(keepends=True)
    for _idx, line in enumerate(lines):
        if line.strip() == "":
            out_lines.append(line)
            continue
        code, comment = _split_code_and_comment(line)
        if comment is None:
            out_lines.append(line)
            continue
        is_line_start = len(code.strip()) == 0
        if _should_preserve_comment(comment, is_line_start=is_line_start):
            out_lines.append(line)
            continue
        newline = ""
        if line.endswith("\r\n"):
            newline = "\r\n"
            code_part = code
        elif line.endswith("\n"):
            newline = "\n"
            code_part = code
        else:
            code_part = code
        if code_part.strip() == "":
            new_line = newline
        else:
            new_line = code_part.rstrip("\r\n") + newline
        out_lines.append(new_line)
        removed += 1
    return "".join(out_lines), removed


def _collect_py_files(paths: list[Path], *, recursive: bool = True) -> list[Path]:
    py_files: list[Path] = []
    for target in paths:
        if target.is_file():
            if target.suffix == ".py":
                py_files.append(target)
        elif target.is_dir():
            pattern = "**/*.py" if recursive else "*.py"
            py_files.extend(target.glob(pattern))
    return sorted({p.resolve() for p in py_files})


def process_file(path: Path, cwd: Path, *, strip_comments: bool) -> tuple[str, int, int] | None:
    rel = str(path.relative_to(cwd))
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        source = path.read_text(encoding="latin-1")
    except Exception:
        return None
    new_source, doc_count = _remove_docstrings_from_source(source)
    comment_count = 0
    if strip_comments and new_source == source:
        pass
    if strip_comments:
        new_source, comment_count = _remove_comments_from_source(new_source)
    if new_source == source:
        return None
    if not _validate_syntax(new_source):
        return None
    try:
        path.write_text(new_source, encoding="utf-8")
    except Exception:
        return None
    return rel, doc_count, comment_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Strip docstrings from Python files (preserves module docstrings). Optionally remove comments."
    )
    parser.add_argument(
        "-c",
        "--comments",
        action="store_true",
        help="Remove comments too (preserve shebangs, # type:, # fmt:, coding cookies).",
    )
    parser.add_argument(
        "targets",
        nargs="*",
        help="Files or directories to process (default: current directory, recursive).",
    )
    args = parser.parse_args()
    cwd = Path.cwd()
    if args.targets:
        targets = [Path(t).resolve() for t in args.targets]
        py_files = _collect_py_files(targets, recursive=True)
    else:
        py_files = get_pyfiles(cwd)
        py_files = sorted(set(py_files))
    if not py_files:
        return
    strip_comments = True
    changed: list[tuple[str, int, int]] = []
    with ProcessPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(process_file, p, cwd, strip_comments=strip_comments): p for p in py_files}
        for fut in as_completed(futures):
            res = fut.result()
            if res is not None:
                changed.append(res)
    for rel, doc_count, comment_count in sorted(changed, key=lambda x: x[0]):
        print(rel)
        if doc_count > 0:
            print(f"  docstrings removed: {doc_count}")
        if strip_comments and comment_count > 0:
            print(f"  comments removed: {comment_count}")


if __name__ == "__main__":
    raise SystemExit(main())
