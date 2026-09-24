from __future__ import annotations

import ast
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dh import get_files

DH_SRC_DIR = Path("~/projects/py/dh/src/dh").expanduser()


def build_dh_mapping(dh_path: Path) -> dict:
    init_file = dh_path / "__init__.py"
    if not init_file.exists():
        raise FileNotFoundError(f"Could not find __init__.py at {init_file}")
    mapping = {}
    tree = ast.parse(init_file.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            module_name = node.module
            module_path = dh_path / f"{module_name}.py"
            for alias in node.names:
                mapping[alias.name] = module_path
    return mapping


class ModuleDependencyAnalyzer(ast.NodeVisitor):
    def __init__(self, global_names):
        self.global_names = global_names
        self.references = set()
        self.imported_modules = []

    def visit_Import(self, node):
        self.imported_modules.append(node)

    def visit_ImportFrom(self, node):
        if node.module != "dh" and node.level == 0:
            self.imported_modules.append(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and node.id in self.global_names:
            self.references.add(node.id)


def get_all_dependencies(path: Path, target_symbol: str) -> tuple[set[str], list[str]]:
    if not path.exists():
        return (set(), [])
    content = path.read_text(encoding="utf-8")
    tree = ast.parse(content)
    lines = content.splitlines()
    nodes_by_name = {}
    global_imports = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nodes_by_name[node.name] = node
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    nodes_by_name[t.id] = node
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            if getattr(node, "module", "") != "dh" and getattr(node, "level", 0) == 0:
                global_imports.append(node)
    if target_symbol not in nodes_by_name:
        return (set(), [])
    needed_symbols = set()
    to_resolve = [target_symbol]
    while to_resolve:
        current = to_resolve.pop(0)
        if current in needed_symbols:
            continue
        needed_symbols.add(current)
        node = nodes_by_name.get(current)
        if node:
            analyzer = ModuleDependencyAnalyzer(nodes_by_name.keys())
            analyzer.visit(node)
            for ref in analyzer.references:
                if ref not in needed_symbols:
                    to_resolve.append(ref)
    needed_imports = set()
    all_code_text = "\n".join(
        "\n".join(lines[nodes_by_name[sym].lineno - 1 : nodes_by_name[sym].end_lineno]) for sym in needed_symbols
    )
    for imp in global_imports:
        imp_text = ast.unparse(imp)
        if isinstance(imp, (ast.Import, ast.ImportFrom)):
            for alias in imp.names:
                name = alias.asname or alias.name
                if name in all_code_text:
                    needed_imports.add(imp_text)
    source_blocks = []
    sorted_symbols = sorted(needed_symbols, key=lambda s: nodes_by_name[s].lineno)
    for sym in sorted_symbols:
        node = nodes_by_name[sym]
        source_blocks.append("\n".join(lines[node.lineno - 1 : node.end_lineno]))
    return (needed_imports, source_blocks)


def process_file(path: Path, mapping: dict):
    path = Path(path)
    if path.resolve() == Path(__file__).resolve():
        return
    try:
        content = path.read_text(encoding="utf-8")
        if "dh" not in content:
            return
        tree = ast.parse(content)
        lines = content.splitlines(keepends=True)
        dh_import_ranges = []
        used_dh_symbols = set()
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "dh":
                dh_import_ranges.append((node.lineno - 1, node.end_lineno))
                for alias in node.names:
                    used_dh_symbols.add(alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "dh":
                        dh_import_ranges.append((node.lineno - 1, node.end_lineno))
        if not used_dh_symbols:
            return
        for start, end in sorted(dh_import_ranges, reverse=True):
            del lines[start:end]
        file_imports = set()
        file_source_blocks = []
        for symbol in used_dh_symbols:
            if symbol in mapping:
                imports, blocks = get_all_dependencies(mapping[symbol], symbol)
                file_imports.update(imports)
                for block in blocks:
                    if block not in file_source_blocks:
                        file_source_blocks.append(block)
            else:
                file_source_blocks.append(f"# WARNING: Source code for '{symbol}' not found.")
        if file_source_blocks:
            injection_parts = []
            if file_imports:
                injection_parts.append("\n".join(file_imports))
            injection_parts.extend(file_source_blocks)
            inlined_code = "\n\n" + "\n\n".join(injection_parts) + "\n\n"
            insert_idx = 0
            if lines and lines[0].startswith("#!"):
                insert_idx = 1
            tree = ast.parse(content)
            last_import_end = 0
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if isinstance(node, ast.ImportFrom) and node.module == "dh":
                        continue
                    if isinstance(node, ast.Import):
                        skip = False
                        for alias in node.names:
                            if alias.name == "dh":
                                skip = True
                                break
                        if skip:
                            continue
                    last_import_end = max(last_import_end, node.end_lineno)
                else:
                    break
            if last_import_end > 0:
                insert_idx = last_import_end
            if insert_idx > 0 and lines[insert_idx - 1].strip():
                inlined_code = "\n" + inlined_code
            new_content = "".join(lines[:insert_idx]) + inlined_code + "".join(lines[insert_idx:])
            path.write_text(new_content, encoding="utf-8")
            print(f"Refactored: {path} -> Inlined: {', '.join(used_dh_symbols)}")
    except Exception as e:
        print(f"Error processing {path}: {e}")


def main():
    try:
        mapping = build_dh_mapping(DH_SRC_DIR)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    cwd = Path.cwd()
    args = sys.argv[1:]
    py_files = [Path(p) for p in args] if args else get_files(cwd, ext=[".py"])
    with ThreadPoolExecutor() as executor:
        executor.map(lambda p: process_file(p, mapping), py_files)


if __name__ == "__main__":
    raise SystemExit(main())
