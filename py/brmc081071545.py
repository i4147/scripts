from __future__ import annotations
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


def _remove_docstrings_from_source(source: str) -> str:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    to_remove = []
    preserve_module = _first_statement_is_docstring(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr):
            continue
        val = getattr(node, "value", None)
        if not isinstance(val, ast.Constant) or not isinstance(val.value, str):
            continue
        if preserve_module and isinstance(getattr(tree, "body", None), list) and tree.body:
            if node is tree.body[0]:
                continue
        if hasattr(node, "lineno") and hasattr(node, "end_lineno"):
            to_remove.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset))
    if not to_remove:
        return source
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
    return new_source


def process_file(path: Path, cwd: Path) -> str | None:
    rel = str(path.relative_to(cwd))
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        source = path.read_text(encoding="latin-1")
    new_source = _remove_docstrings_from_source(source)
    if new_source != source:
        path.write_text(new_source, encoding="utf-8")
        return rel
    return None


def main() -> None:
    cwd = Path(".").resolve()
    py_files = get_pyfiles(cwd)
    changed = []
    with ProcessPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(process_file, p, cwd) for p in py_files]
        for fut in as_completed(futures):
            rel = fut.result()
            if rel is not None:
                changed.append(rel)
    for rel in sorted(changed):
        print(rel)


if __name__ == "__main__":
    main()
