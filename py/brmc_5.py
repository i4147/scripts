import ast
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Tuple


class DocstringRemover(ast.NodeTransformer):
    def __init__(self) -> None:
        self.removed_count = 0

    def remove_docstring(self, node) -> Optional[str]:
        if not node.body:
            return None

        first_node = node.body[0]

        if isinstance(first_node, ast.Expr):
            is_docstring = False

            if isinstance(first_node.value, ast.Constant):
                is_docstring = True
            elif isinstance(first_node.value, ast.Constant) and isinstance(first_node.value.value, str):
                is_docstring = True

            if is_docstring:
                if len(node.body) == 1:
                    node.body = [ast.Pass()]
                    return "replaced_with_pass"
                else:
                    node.body = node.body[1:]
                    return "removed"

        return None

    def visit_ClassDef(self, node):
        result = self.remove_docstring(node)
        if result == "removed":
            self.removed_count += 1
        elif result == "replaced_with_pass":
            self.removed_count += 1

        self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node):
        result = self.remove_docstring(node)
        if result == "removed":
            self.removed_count += 1
        elif result == "replaced_with_pass":
            self.removed_count += 1

        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node):
        result = self.remove_docstring(node)
        if result == "removed":
            self.removed_count += 1
        elif result == "replaced_with_pass":
            self.removed_count += 1

        self.generic_visit(node)
        return node


def has_module_docstring(tree: ast.AST) -> bool:
    if not tree.body:
        return False

    first_node = tree.body[0]
    if isinstance(first_node, ast.Expr):
        if isinstance(first_node.value, ast.Constant):
            return True
        elif isinstance(first_node.value, ast.Constant) and isinstance(first_node.value.value, str):
            return True

    return False


def process_file(file_path: Path) -> Tuple[Path, bool, int, float]:
    start_time = time.perf_counter()

    try:
        content = file_path.read_text(encoding="utf-8")

        tree = ast.parse(content)

        has_docstring = has_module_docstring(tree)

        remover = DocstringRemover()
        modified_tree = remover.visit(tree)
        ast.fix_missing_locations(modified_tree)

        if remover.removed_count > 0:
            if has_docstring:
                original_docstring = ast.get_docstring(tree)
                if original_docstring:
                    docstring_node = ast.Expr(
                        value=ast.Constant(value=original_docstring)
                        if hasattr(ast, "Constant")
                        else ast.Str(s=original_docstring)
                    )

                    modified_tree.body.insert(0, docstring_node)

            try:
                import astor

                new_content = astor.to_source(modified_tree)
            except ImportError:
                try:
                    new_content = ast.unparse(modified_tree)
                except AttributeError:
                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    return file_path, False, 0, elapsed_ms

            try:
                _ = ast.parse(new_content)
                file_path.write_text(new_content, encoding="utf-8")
                was_modified = True
            except:
                print("ast parse error")
                return file_path, False, 0, elapsed_ms
        else:
            was_modified = False

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return file_path, was_modified, remover.removed_count, elapsed_ms

    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        print(f"Error processing {file_path}: {e}", file=sys.stderr)
        return file_path, False, 0, elapsed_ms


def find_python_files(directory: Path) -> list:
    return list(directory.rglob("*.py"))


def format_report(file_path: Path, was_modified: bool, count: int, elapsed_ms: float) -> str:
    if was_modified:
        status = f"{count} docstring{'s' if count != 1 else ''} removed"
        return f"{file_path} {elapsed_ms:.0f}ms ({status})"
    else:
        return f"{file_path} {elapsed_ms:.0f}ms (no change)"


def main() -> None:
    current_dir = Path.cwd()

    print(f"Scanning Python files in: {current_dir}")
    print("-" * 60)

    python_files = find_python_files(current_dir)

    if not python_files:
        print("No Python files found.")
        return

    print(f"Found {len(python_files)} Python file(s) to process\n")

    results = []
    total_start = time.perf_counter()

    with ProcessPoolExecutor() as executor:
        future_to_file = {executor.submit(process_file, file_path): file_path for file_path in python_files}

        for future in as_completed(future_to_file):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                file_path = future_to_file[future]
                print(f"Error processing {file_path}: {e}", file=sys.stderr)

    total_elapsed = (time.perf_counter() - total_start) * 1000

    results.sort(key=lambda x: str(x[0]))

    total_removed = 0
    total_modified = 0

    for file_path, was_modified, count, elapsed_ms in results:
        print(format_report(file_path, was_modified, count, elapsed_ms))
        if was_modified:
            total_removed += count
            total_modified += 1

    print("-" * 60)
    print(f"Summary: {total_modified} file(s) modified, {total_removed} docstring(s) removed")
    print(f"Total time: {total_elapsed:.0f}ms")

    if len(results) < len(python_files):
        skipped = len(python_files) - len(results)
        print(f"Warning: {skipped} file(s) could not be processed")


if __name__ == "__main__":
    main()
