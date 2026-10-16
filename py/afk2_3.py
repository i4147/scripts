import ast
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dh import get_pyfiles


@dataclass
class ImportInfo:
    name: str
    alias: Optional[str]
    line: int
    col: int
    end_line: int
    is_from_import: bool
    module: Optional[str] = None
    names: List[str] = None


class ImportAnalyzer(ast.NodeVisitor):
    def __init__(self) -> None:
        self.imports = []
        self.used_names = set()
        self.defined_names = set()
        self.current_scope = []

    def visit_Import(self, node) -> None:
        for alias in node.names:
            base_name = alias.name.split(".")[0]
            self.imports.append(
                ImportInfo(
                    name=alias.name,
                    alias=alias.asname,
                    line=node.lineno,
                    col=node.col_offset,
                    end_line=node.end_lineno or node.lineno,
                    is_from_import=False,
                )
            )
        self.generic_visit(node)

    def visit_ImportFrom(self, node) -> None:
        if node.module is None:
            self.generic_visit(node)
            return
        for alias in node.names:
            if alias.name == "*":
                continue
            self.imports.append(
                ImportInfo(
                    name=alias.name,
                    alias=alias.asname,
                    line=node.lineno,
                    col=node.col_offset,
                    end_line=node.end_lineno or node.lineno,
                    is_from_import=True,
                    module=node.module,
                    names=[alias.name],
                )
            )
        self.generic_visit(node)

    def visit_Name(self, node) -> None:
        if isinstance(node.ctx, (ast.Load, ast.AugLoad)):
            self.used_names.add(node.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node) -> None:
        self.defined_names.add(node.name)
        for arg in node.args.args:
            self.defined_names.add(arg.arg)
        if node.args.vararg:
            self.defined_names.add(node.args.vararg.arg)
        if node.args.kwarg:
            self.defined_names.add(node.args.kwarg.arg)
        self.generic_visit(node)

    def visit_ClassDef(self, node) -> None:
        self.defined_names.add(node.name)
        self.generic_visit(node)

    def visit_Assign(self, node) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.defined_names.add(target.id)
            elif isinstance(target, (ast.Tuple, ast.List)):
                for elt in target.elts:
                    if isinstance(elt, ast.Name):
                        self.defined_names.add(elt.id)
        self.generic_visit(node)

    def visit_AnnAssign(self, node) -> None:
        if isinstance(node.target, ast.Name):
            self.defined_names.add(node.target.id)
        self.generic_visit(node)

    def visit_alias(self, node) -> None:
        if node.asname:
            if node.asname in self.used_names:
                self.used_names.add(node.name.split(".")[0])
        self.generic_visit(node)


class ImportRemover:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.removed_imports = []

    def analyze(self) -> List[ImportInfo]:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                content = f.read()
            tree = ast.parse(content, filename=str(self.path))
            analyzer = ImportAnalyzer()
            analyzer.visit(tree)
            unused_imports = []
            for imp in analyzer.imports:
                name_to_check = imp.alias if imp.alias else imp.name
                if imp.is_from_import and imp.names:
                    pass
                if name_to_check not in analyzer.used_names and name_to_check not in analyzer.defined_names:
                    unused_imports.append(imp)
            return unused_imports
        except SyntaxError as e:
            print(f"Syntax error in {self.path}: {e}", file=sys.stderr)
            return []
        except Exception as e:
            print(f"Error analyzing {self.path}: {e}", file=sys.stderr)
            return []

    def remove_unused_imports(self, unused_imports: List[ImportInfo]) -> List[str]:
        if not unused_imports:
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            lines_to_remove = sorted(set([imp.line for imp in unused_imports]), reverse=True)
            removed_imports = []
            for line_num in lines_to_remove:
                if 1 <= line_num <= len(lines):
                    line_content = lines[line_num - 1].rstrip()
                    lines.pop(line_num - 1)
                    for imp in unused_imports:
                        if imp.line == line_num:
                            import_name = imp.alias if imp.alias else imp.name
                            removed_imports.append(f"{import_name} (line {line_num})")
            if removed_imports:
                with open(self.path, "w", encoding="utf-8") as f:
                    f.writelines(lines)
            return removed_imports
        except Exception as e:
            print(f"Error removing imports from {self.path}: {e}", file=sys.stderr)
            return []

    def process(self) -> Tuple[Path, List[str]]:
        unused_imports = self.analyze()
        if unused_imports:
            removed = self.remove_unused_imports(unused_imports)
            return (self.path, removed)
        return (self.path, [])


def find_files(root_path: Path) -> List[Path]:
    files = []
    if root_path.is_file():
        if root_path.suffix == ".py":
            files.append(root_path)
    else:
        for path in root_path.rglob("*.py"):
            if any(
                (
                    part.startswith(".") or part in ["__pycache__", "venv", "env", ".venv", "node_modules"]
                    for part in path.parts
                )
            ):
                continue
            files.append(path)
    return files


def process_file(path: Path) -> Tuple[Path, List[str]]:
    path = Path(path)
    try:
        remover = ImportRemover(path)
        return remover.process()
    except Exception as e:
        print(f"Failed to process {path}: {e}", file=sys.stderr)
        return (path, [])


def print_summary(results: Dict[Path, List[str]], total_files: int, total_imports_removed: int) -> None:
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"\nTotal files processed: {total_files}")
    print(f"Files modified: {len([r for r in results.values() if r])}")
    print(f"Total unused imports removed: {total_imports_removed}")
    if results:
        print("\nModified files:")
        for path, removed in results.items():
            if removed:
                print(f"\n  📄 {path}")
                for imp in removed:
                    print(f"     ✗ {imp}")
    print("\n" + "=" * 60)


def main() -> None:

    args = sys.argv[1:]

    cwd = Path.cwd()
    files = [Path(p) for p in args] if args else get_pyfiles(cwd)
    if len(files) == 1:
        process_file(files[0])
        sys.exit(1)

    num_workers = 6
    results = {}
    total_imports_removed = 0
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        future_to_file = {executor.submit(process_file, path): path for path in files}
        from concurrent.futures import as_completed

        for i, future in enumerate(as_completed(future_to_file), 1):
            path = future_to_file[future]
            try:
                path_result, removed_imports = future.result()
                results[path_result] = removed_imports
                total_imports_removed += len(removed_imports)
                if removed_imports:
                    print(f"[{i}/{len(files)}] ✓ {path_result} - Removed {len(removed_imports)} imports")
                else:
                    print(f"[{i}/{len(files)}] ○ {path_result} - No unused imports")
            except Exception as e:
                print(f"[{i}/{len(files)}] ✗ Failed to process {path}: {e}", file=sys.stderr)
                results[path] = []
    print_summary(results, len(files), total_imports_removed)


if __name__ == "__main__":
    main()
