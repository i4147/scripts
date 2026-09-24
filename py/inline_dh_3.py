import ast
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

DH_SRC_DIR = Path("~/isaac/pkgs/dh/src/dh").expanduser()
TARGET_DIR = Path(".")


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


def get_all_dependencies(file_path: Path, target_symbol: str) -> tuple[set[str], list[str]]:
    if not file_path.exists():
        return (set(), [])
    content = file_path.read_text(encoding="utf-8")
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
        (lines[nodes_by_name[sym].lineno - 1 : nodes_by_name[sym].end_lineno] for sym in needed_symbols)
    )
    for imp in global_imports:
        imp_text = ast.unparse(imp)
        if isinstance(imp, ast.Import):
            for alias in imp.names:
                name = alias.asname or alias.name
                if name in all_code_text:
                    needed_imports.add(imp_text)
        elif isinstance(imp, ast.ImportFrom):
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


class DHImportTransformer(ast.NodeTransformer):
    def __init__(self):
        self.used_dh_symbols = set()

    def visit_ImportFrom(self, node):
        if node.module == "dh":
            for alias in node.names:
                self.used_dh_symbols.add(alias.name)
            return None
        return node


def process_file(file_path: Path, mapping: dict):
    if file_path.resolve() == Path(__file__).resolve():
        return
    try:
        content = file_path.read_text(encoding="utf-8")
        if "dh" not in content:
            return
        tree = ast.parse(content)
        transformer = DHImportTransformer()
        modified_tree = transformer.visit(tree)
        if not transformer.used_dh_symbols:
            return
        clean_lines = content.splitlines()
        import_lines = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "dh":
                import_lines.append((node.lineno - 1, node.end_lineno))
        for start, end in sorted(import_lines, reverse=True):
            del clean_lines[start:end]
        file_imports = set()
        file_source_blocks = []
        for symbol in transformer.used_dh_symbols:
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
            new_content = "\n\n".join(injection_parts) + "\n\n" + "\n".join(clean_lines) + "\n"
            file_path.write_text(new_content, encoding="utf-8")
            print(f"Refactored: {file_path} -> Standalone inlined: {', '.join(transformer.used_dh_symbols)}")
    except Exception as e:
        print(f"Error processing {file_path}: {e}")


def main():
    print("Mapping source definitions from dh...")
    mapping = build_dh_mapping(DH_SRC_DIR)
    print("Finding target files recursively...")
    py_files = list(TARGET_DIR.rglob("*.py"))
    print(f"Processing {len(py_files)} files using parallel threads...")
    with ThreadPoolExecutor() as executor:
        executor.map(lambda p: process_file(p, mapping), py_files)
    print("Done!")


if __name__ == "__main__":
    main()
