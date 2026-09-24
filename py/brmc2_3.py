import ast
import sys
from collections.abc import Iterable, Sequence
from multiprocessing import Pool
from pathlib import Path
from loguru import logger

MAX_WORKERS = 8
"""Fixed number of worker processes used for concurrent file processing."""


class DocstringRemover(ast.NodeTransformer):
    def __init__(self):
        self.is_module = True
        self.preserve_module_docstring = True

    def visit_Module(self, node):
        self.is_module = True
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            module_docstring = node.body[0]
            remaining_body = self._visit_body(node.body[1:])
            node.body = [module_docstring] + remaining_body
        else:
            node.body = self._visit_body(node.body)
        self.is_module = False
        return node

    def _visit_body(self, body):
        new_body = []
        for stmt in body:
            new_body.append(self.visit(stmt))
        return new_body

    def visit_FunctionDef(self, node):
        return self._process_function_like(node)

    def visit_AsyncFunctionDef(self, node):
        return self._process_function_like(node)

    def visit_ClassDef(self, node):
        node.body = self._remove_docstring_from_body(node.body)
        node.decorator_list = [self.visit(dec) for dec in node.decorator_list]
        return node

    def _process_function_like(self, node):
        node.body = self._remove_docstring_from_body(node.body)
        node.decorator_list = [self.visit(dec) for dec in node.decorator_list]
        return node

    def _remove_docstring_from_body(self, body):
        if not body:
            return body
        if (
            isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body = body[1:]
        new_body = [self.visit(stmt) for stmt in body]
        if not new_body:
            new_body = [ast.Pass()]
        return new_body


def remove_docstrings_from_code(source_code):
    try:
        tree = ast.parse(source_code)
        transformer = DocstringRemover()
        new_tree = transformer.visit(tree)
        ast.fix_missing_locations(new_tree)
        compile(new_tree, "<transformed>", "exec")
        return ast.unparse(new_tree)
    except SyntaxError as exc:
        logger.error(f"Syntax error in transformed code: {exc}")
        return None
    except Exception as exc:
        logger.error(f"Error processing code: {exc}")
        return None


def validate_python_code(code):
    try:
        ast.parse(code)
        compile(code, "<string>", "exec")
        return True
    except (SyntaxError, ValueError) as exc:
        logger.error(f"Code validation failed: {exc}")
        return False


def process_file(path):
    try:
        original_code = path.read_text(encoding="utf-8")
        if not validate_python_code(original_code):
            return (path, False, "Original code validation failed")
        modified_code = remove_docstrings_from_code(original_code)
        if modified_code is None:
            return (path, False, "Docstring removal failed")
        if not validate_python_code(modified_code):
            return (path, False, "Modified code validation failed")
        path.write_text(modified_code, encoding="utf-8")
        return (path, True, None)
    except Exception as exc:
        return (path, False, str(exc))


def find_python_files(paths):
    python_files = []
    for path in paths:
        if path.is_file() and path.suffix == ".py":
            python_files.append(path)
        elif path.is_dir():
            python_files.extend(path.rglob("*.py"))
    return sorted(set(python_files))


def main():
    if len(sys.argv) > 1:
        input_paths = [Path(arg) for arg in sys.argv[1:]]
    else:
        input_paths = [Path.cwd()]
    for path in input_paths:
        if not path.exists():
            logger.error(f"Path does not exist: {path}")
            return 1
    python_files = find_python_files(input_paths)
    if not python_files:
        logger.warning("No Python files found to process")
        return 0
    print(f"Found {len(python_files)} Python file(s) to process")
    successful = 0
    failed = 0
    with Pool(processes=MAX_WORKERS) as pool:
        async_results = [pool.apply_async(process_file, (path,)) for path in python_files]
        for async_result in async_results:
            path, success, error = async_result.get()
            if success:
                print(f"✓ Processed: {path}")
                successful += 1
            else:
                logger.error(f"✗ Failed: {path} - {error}")
                failed += 1
    print(f"\n{'=' * 40}")
    print("Processing complete:")
    print(f"  Successful: {successful}")
    print(f"  Failed:     {failed}")
    print(f"  Total:      {len(python_files)}")
    print(f"{'=' * 40}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
