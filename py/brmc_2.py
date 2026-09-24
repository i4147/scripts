import ast
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

ProcessResult: TypeAlias = "FileProcessingResult"
ASTOR_AVAILABLE: Final[bool] = bool(__import__("astor", fromlist=["to_source"]) if False else True)
try:
    import astor

    ASTOR_AVAILABLE = True
except ImportError:
    ASTOR_AVAILABLE = False


@dataclass(slots=True, frozen=True)
class FileProcessingResult:
    file_path: Path
    was_modified: bool
    removed_count: int
    elapsed_ms: float
    error: str | None = None


class DocstringRemover(ast.NodeTransformer):
    __slots__ = ("removed_count",)

    def __init__(self) -> None:
        super().__init__()
        self.removed_count = 0

    @staticmethod
    def _is_docstring_node(node: ast.AST) -> bool:
        if not isinstance(node, ast.Expr):
            return False
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return True
        if hasattr(ast, "Str") and isinstance(value, ast.Str):
            return True
        return False

    def _remove_docstring(self, node: ast.AST) -> bool:
        if not hasattr(node, "body") or not node.body:
            return False
        if self._is_docstring_node(node.body[0]):
            self.removed_count += 1
            if len(node.body) == 1:
                node.body = [ast.Pass()]
            else:
                node.body = node.body[1:]
            return True
        return False

    def visit_Module(self, node: ast.Module) -> ast.Module:
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        self._remove_docstring(node)
        self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        self._remove_docstring(node)
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
        self._remove_docstring(node)
        self.generic_visit(node)
        return node


def has_module_docstring(tree: ast.Module) -> bool:
    if not tree.body:
        return False
    first_node = tree.body[0]
    return isinstance(first_node, ast.Expr) and isinstance(
        first_node.value, (ast.Constant, getattr(ast, "Str", type(None)))
    )


def ast_to_source(tree: ast.AST) -> str | None:
    if ASTOR_AVAILABLE:
        try:
            return astor.to_source(tree)
        except Exception:
            pass
    if hasattr(ast, "unparse"):
        return ast.unparse(tree)
    return None


def process_file(file_path: Path) -> FileProcessingResult:
    start_time = time.perf_counter()
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content)
        has_module_doc = has_module_docstring(tree)
        module_docstring = ast.get_docstring(tree, clean=False) if has_module_doc else None
        remover = DocstringRemover()
        modified_tree = remover.visit(tree)
        ast.fix_missing_locations(modified_tree)
        if remover.removed_count == 0:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            return FileProcessingResult(file_path, False, 0, elapsed_ms)
        if has_module_doc and module_docstring is not None:
            if hasattr(ast, "Constant"):
                docstring_node = ast.Expr(value=ast.Constant(value=module_docstring))
            else:
                docstring_node = ast.Expr(value=ast.Str(s=module_docstring))
            modified_tree.body.insert(0, docstring_node)
        new_content = ast_to_source(modified_tree)
        if new_content is None:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            return FileProcessingResult(file_path, False, 0, elapsed_ms, error="No AST to source converter available")
        try:
            ast.parse(new_content)
        except SyntaxError as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            return FileProcessingResult(file_path, False, 0, elapsed_ms, error=f"Generated code has syntax error: {e}")
        file_path.write_text(new_content, encoding="utf-8")
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return FileProcessingResult(file_path, True, remover.removed_count, elapsed_ms)
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        error_msg = f"{type(e).__name__}: {e}"
        print(f"Error processing {file_path}: {error_msg}", file=sys.stderr)
        return FileProcessingResult(file_path, False, 0, elapsed_ms, error=error_msg)


def find_python_files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.py"))


def format_report(result: FileProcessingResult) -> str:
    if result.error:
        return f"{result.file_path} {result.elapsed_ms:.0f}ms (ERROR: {result.error})"
    if result.was_modified:
        count = result.removed_count
        plural = "s" if count != 1 else ""
        return f"{result.file_path} {result.elapsed_ms:.0f}ms ({count} docstring{plural} removed)"
    return f"{result.file_path} {result.elapsed_ms:.0f}ms (no change)"


def main() -> None:
    current_dir = Path.cwd()
    print(f"Scanning Python files in: {current_dir}")
    print("-" * 60)
    python_files = find_python_files(current_dir)
    if not python_files:
        print("No Python files found.")
        return
    print(f"Found {len(python_files)} Python file(s) to process\n")
    results: list[FileProcessingResult] = []
    total_start = time.perf_counter()
    with ProcessPoolExecutor() as executor:
        future_to_file = {executor.submit(process_file, file_path): file_path for file_path in python_files}
        for future in as_completed(future_to_file):
            file_path = future_to_file[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                print(f"Error processing {file_path}: {type(e).__name__}: {e}", file=sys.stderr)
                results.append(FileProcessingResult(file_path, False, 0, 0, error=str(e)))
    total_elapsed = (time.perf_counter() - total_start) * 1000
    results.sort(key=lambda x: str(x.file_path))
    total_removed = 0
    total_modified = 0
    total_errors = 0
    for result in results:
        print(format_report(result))
        if result.was_modified:
            total_removed += result.removed_count
            total_modified += 1
        elif result.error:
            total_errors += 1
    print("-" * 60)
    print(f"Summary: {total_modified} file(s) modified, {total_removed} docstring(s) removed")
    print(f"Total time: {total_elapsed:.0f}ms")
    if total_errors > 0:
        print(f"⚠ Warning: {total_errors} file(s) had errors during processing")


if __name__ == "__main__":
    main()
