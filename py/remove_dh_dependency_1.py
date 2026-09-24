import ast
import os
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple
import importlib.util


DH_SOURCE_PATH = Path.home() / "isaac" / "pkgs" / "dh" / "src" / "dh"
DH_MODULE_NAME = "dh"
CURRENT_DIR = Path(".")


class DHModuleAnalyzer:
    def __init__(self, dh_path: Path):
        self.dh_path = dh_path
        self.definitions: Dict[str, str] = {}
        self.module_mapping: Dict[str, Set[str]] = {}
        self._load_dh_definitions()

    def _load_dh_definitions(self):
        if not self.dh_path.exists():
            raise FileNotFoundError(f"DH module path not found: {self.dh_path}")

        py_files = list(self.dh_path.glob("*.py"))

        for py_file in py_files:
            if py_file.name == "__init__.py":
                continue

            module_name = py_file.stem
            self.module_mapping[module_name] = set()

            try:
                with open(py_file, "r", encoding="utf-8") as f:
                    content = f.read()

                tree = ast.parse(content)

                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                        func_name = node.name
                        start_line = node.lineno - 1
                        end_line = node.end_lineno

                        lines = content.split("\n")
                        func_source = "\n".join(lines[start_line:end_line])

                        self.definitions[func_name] = func_source
                        self.module_mapping[module_name].add(func_name)

            except Exception as e:
                print(f"Warning: Could not parse {py_file}: {e}", file=sys.stderr)

    def get_definition(self, func_name: str) -> str:
        return self.definitions.get(func_name, None)

    def get_all_definitions(self) -> Dict[str, str]:
        return self.definitions.copy()


class ImportRemover(ast.NodeTransformer):
    def __init__(self, definitions: Dict[str, str]):
        self.definitions = definitions
        self.imports_to_remove: List[ast.stmt] = []
        self.inlined_code: List[str] = []
        self.imported_names: Dict[str, str] = {}

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.stmt:
        if node.module and (node.module == DH_MODULE_NAME or node.module.startswith(f"{DH_MODULE_NAME}.")):
            for alias in node.names:
                name = alias.name
                if name in self.definitions:
                    self.imported_names[alias.asname or name] = name
                    self.inlined_code.append(self.definitions[name])

            return None

        return node

    def visit_Import(self, node: ast.Import) -> ast.stmt:
        if any(alias.name == DH_MODULE_NAME or alias.name.startswith(f"{DH_MODULE_NAME}.") for alias in node.names):
            return None

        return node


class PythonFileProcessor:
    def __init__(self, dh_analyzer: DHModuleAnalyzer):
        self.analyzer = dh_analyzer
        self.definitions = dh_analyzer.get_all_definitions()

    def process_file(self, file_path: Path) -> Tuple[bool, str]:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                original_content = f.read()

            tree = ast.parse(original_content)
            transformer = ImportRemover(self.definitions)
            new_tree = transformer.visit(tree)

            if not transformer.imported_names:
                return False, original_content

            lines = original_content.split("\n")

            import_end_idx = 0
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith("import ") or stripped.startswith("from "):
                    import_end_idx = i + 1
                elif stripped and not stripped.startswith("#"):
                    break

            filtered_lines = []
            for i, line in enumerate(lines):
                if any(f"from {DH_MODULE_NAME}" in line or f"import {DH_MODULE_NAME}" in line for _ in [None]):
                    if "from dh import" in line or "import dh" in line:
                        continue
                filtered_lines.append(line)

            new_lines = filtered_lines[:import_end_idx]

            if transformer.inlined_code:
                new_lines.append("\n# ===== Inlined from dh module =====\n")
                new_lines.extend(transformer.inlined_code)
                new_lines.append("\n# ===== End of inlined code =====\n")

            new_lines.extend(filtered_lines[import_end_idx:])

            new_content = "\n".join(new_lines)

            return True, new_content

        except SyntaxError as e:
            print(f"Warning: Syntax error in {file_path}: {e}", file=sys.stderr)
            return False, original_content
        except Exception as e:
            print(f"Warning: Error processing {file_path}: {e}", file=sys.stderr)
            return False, original_content

    def process_file_and_save(self, file_path: Path, dry_run: bool = False) -> bool:
        modified, new_content = self.process_file(file_path)

        if modified:
            if not dry_run:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                print(f"✓ Updated: {file_path}")
            else:
                print(f"◇ Would update: {file_path}")

            return True

        return False


class ProjectCleaner:
    def __init__(self, root_dir: Path = CURRENT_DIR, dh_path: Path = DH_SOURCE_PATH):
        self.root_dir = root_dir.resolve()
        self.dh_path = dh_path.resolve()
        self.analyzer = DHModuleAnalyzer(self.dh_path)
        self.processor = PythonFileProcessor(self.analyzer)
        self.processed_files: List[Path] = []
        self.modified_files: List[Path] = []

    def find_python_files(self) -> List[Path]:
        return [f for f in self.root_dir.rglob("*.py") if not any(part.startswith(".") for part in f.parts)]

    def process_project(self, dry_run: bool = False):
        py_files = self.find_python_files()

        if not py_files:
            print("No Python files found.")
            return

        print(f"Found {len(py_files)} Python files to process.")
        print(f"Loaded {len(self.analyzer.definitions)} definitions from dh module.\n")

        modified_count = 0
        for py_file in py_files:
            self.processed_files.append(py_file)
            if self.processor.process_file_and_save(py_file, dry_run):
                self.modified_files.append(py_file)
                modified_count += 1

        print(f"\n{'=' * 60}")
        print(f"Processing complete!")
        print(f"Total files processed: {len(self.processed_files)}")
        print(f"Files modified: {modified_count}")

        if dry_run:
            print(f"\nDry run mode - no changes saved.")

        if self.modified_files:
            print(f"\nModified files:")
            for f in self.modified_files:
                print(f"  - {f.relative_to(self.root_dir)}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Remove dependencies on 'dh' module by inlining function code.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be changed without modifying files.")
    parser.add_argument(
        "--dh-path", type=Path, default=DH_SOURCE_PATH, help=f"Path to dh module (default: {DH_SOURCE_PATH})"
    )
    parser.add_argument(
        "--root", type=Path, default=CURRENT_DIR, help="Root directory to process (default: current directory)"
    )

    args = parser.parse_args()

    try:
        cleaner = ProjectCleaner(root_dir=args.root, dh_path=args.dh_path)
        cleaner.process_project(dry_run=args.dry_run)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
