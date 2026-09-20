from __future__ import annotations
import ast
from pathlib import Path
from typing import List, Tuple


def has_non_head_imports(source: str) -> Tuple[bool, List[str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return (False, [])
    imports = []
    first_non_import_line = None
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(node)
            continue
        if isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant):
            if isinstance(node.value.value, str):
                if first_non_import_line is None:
                    first_non_import_line = node.lineno
                continue
        first_non_import_line = node.lineno
        break
    if first_non_import_line is None or not imports:
        return (False, [])
    bad_lines = sorted({n.lineno for n in imports if n.lineno > first_non_import_line})
    return (len(bad_lines) > 0, [str(ln) for ln in bad_lines])


def inspect_file(path: Path) -> List[Tuple[int, List[str]]]:
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        source = path.read_text(encoding="latin-1")
    bad, bad_lines = has_non_head_imports(source)
    if not bad:
        return []
    return [(0, bad_lines)]


def main() -> None:
    root = Path(".").resolve()
    py_files = [p for p in root.rglob("*.py") if p.is_file()]
    results = []
    for p in py_files:
        bad_reports = inspect_file(p)
        if bad_reports:
            bad_lines = bad_reports[0][1]
            results.append((p, bad_lines))
    if results:
        for p, lines in sorted(results, key=lambda x: str(x[0])):
            print(f"{p}: import statements not only at file head (import line(s): {', '.join(lines)})")
        raise SystemExit(1)
    else:
        print("OK: No Python files found with imports after non-import statements at module level.")


if __name__ == "__main__":
    main()
