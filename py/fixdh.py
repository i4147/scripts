from __future__ import annotations

import ast
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dh import get_files

DH_SRC_DIR = Path("~/projects/py/dh/src/dh").expanduser()


def build_dh_public_mapping(dh_path: Path) -> dict[str, Path]:
    init_file = dh_path / "__init__.py"
    if not init_file.exists():
        raise FileNotFoundError(f"Could not find __init__.py at {init_file}")
    mapping = {}
    tree = ast.parse(init_file.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            module_path = dh_path / f"{node.module}.py"
            for alias in node.names:
                mapping[alias.name] = module_path
    return mapping


def build_dh_symbol_index(dh_path: Path) -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    for py_file in get_files(dh_path, ext=[".py"]):
        try:
            content = py_file.read_text(encoding="utf-8")
            tree = ast.parse(content)
        except (SyntaxError, UnicodeDecodeError):
            continue
        lines = content.splitlines()
        for node in tree.body:
            name = None
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = node.name
            elif isinstance(node, ast.Assign):
                if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    name = node.targets[0].id
            if name is None:
                continue
            src = "\n".join(lines[node.lineno - 1 : node.end_lineno]).strip()
            index.setdefault(name, set()).add(src)
    return index


def is_import_used(node: ast.Import | ast.ImportFrom, text: str) -> bool:
    for alias in node.names:
        bound_name = alias.asname or alias.name.split(".")[0]
        if re.search(rf"\b{re.escape(bound_name)}\b", text):
            return True
    return False


def process_file(path: Path, public_map: dict[str, Path], symbol_index: dict[str, set[str]]):
    path = Path(path)
    if path.resolve() == Path(__file__).resolve():
        return
    try:
        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content)
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"Skipping {path}: {e}")
        return
    lines = content.splitlines(keepends=True)
    to_remove_ranges = []
    to_import = set()
    for node in tree.body:
        name = None
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        if name is None or name not in symbol_index:
            continue
        node_src = "\n".join(lines[node.lineno - 1 : node.end_lineno]).strip()
        if node_src not in symbol_index[name]:
            continue
        to_remove_ranges.append((node.lineno - 1, node.end_lineno))
        if name in public_map:
            to_import.add(name)
    if not to_remove_ranges:
        return
    for start, end in sorted(to_remove_ranges, reverse=True):
        del lines[start:end]
    remaining_text = "".join(lines)
    try:
        remaining_tree = ast.parse(remaining_text)
    except SyntaxError:
        remaining_tree = None
    if remaining_tree is not None:
        import_removal_ranges = []
        for node in remaining_tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                stmt_text = "".join(lines[node.lineno - 1 : node.end_lineno])
                rest_text = remaining_text.replace(stmt_text, "", 1)
                if not is_import_used(node, rest_text):
                    import_removal_ranges.append((node.lineno - 1, node.end_lineno))
        for start, end in sorted(import_removal_ranges, reverse=True):
            del lines[start:end]
    new_content = "".join(lines)
    if to_import:
        import_line = f"from dh import {', '.join(sorted(to_import))}\n"
        body_lines = new_content.splitlines(keepends=True)
        insert_idx = 1 if body_lines and body_lines[0].startswith("#!") else 0
        body_lines.insert(insert_idx, import_line)
        new_content = "".join(body_lines)
    if new_content != content:
        path.write_text(new_content, encoding="utf-8")
        label = ", ".join(sorted(to_import)) if to_import else "(internal helpers only)"
        print(f"Reverted: {path} -> Restored import: {label}")


def main():
    try:
        public_map = build_dh_public_mapping(DH_SRC_DIR)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    symbol_index = build_dh_symbol_index(DH_SRC_DIR)
    cwd = Path.cwd()
    args = sys.argv[1:]
    py_files = [Path(p) for p in args] if args else get_files(cwd, ext=[".py"])
    with ThreadPoolExecutor() as executor:
        executor.map(lambda p: process_file(p, public_map, symbol_index), py_files)


if __name__ == "__main__":
    raise SystemExit(main())
