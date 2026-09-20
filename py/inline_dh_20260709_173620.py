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


def extract_source_definitions(mapping: dict) -> dict:
    extracted = {}
    
    files_to_read = {}
    for obj_name, file_path in mapping.items():
        files_to_read.setdefault(file_path, []).append(obj_name)

    for file_path, obj_names in files_to_read.items():
        if not file_path.exists():
            continue

        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content)
        lines = content.splitlines()

        for node in tree.body:
            
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name in obj_names:
                    
                    extracted[node.name] = "\n".join(lines[node.lineno - 1 : node.end_lineno])
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in obj_names:
                        extracted[target.id] = "\n".join(lines[node.lineno - 1 : node.end_lineno])
    return extracted


class DHImportTransformer(ast.NodeTransformer):

    def __init__(self):
        self.used_dh_symbols = set()
        self.should_remove = False

    def visit_Import(self, node):
        
        for alias in node.names:
            if alias.name == "dh":
                
                pass
        return node

    def visit_ImportFrom(self, node):
        
        if node.module == "dh":
            for alias in node.names:
                self.used_dh_symbols.add(alias.name)
            return None  
        return node


def process_file(file_path: Path, source_bank: dict):
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

        
        ast.fix_missing_locations(modified_tree)
        clean_lines = content.splitlines()

        
        
        import_lines = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "dh":
                import_lines.append((node.lineno - 1, node.end_lineno))

        
        for start, end in sorted(import_lines, reverse=True):
            del clean_lines[start:end]

        
        injections = []
        for symbol in transformer.used_dh_symbols:
            if symbol in source_bank:
                injections.append(source_bank[symbol])
            else:
                injections.append(f"# WARNING: Source code for '{symbol}' not found in dh source.")

        if injections:
            
            new_content = "\n\n".join(injections) + "\n\n" + "\n".join(clean_lines) + "\n"
            file_path.write_text(new_content, encoding="utf-8")
            print(f"Refactored: {file_path} (Injected: {', '.join(transformer.used_dh_symbols)})")

    except Exception as e:
        print(f"Error processing {file_path}: {e}")


def main():
    print("Mapping source definitions from dh...")
    mapping = build_dh_mapping(DH_SRC_DIR)
    source_bank = extract_source_definitions(mapping)

    print("Finding target files recursively...")
    py_files = list(TARGET_DIR.rglob("*.py"))

    print(f"Processing {len(py_files)} files using parallel threads...")
    with ThreadPoolExecutor() as executor:
        executor.map(lambda p: process_file(p, source_bank), py_files)

    print("Done!")


if __name__ == "__main__":
    main()
