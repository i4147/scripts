from __future__ import annotations

import ast
import logging
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class DocstringRemover(ast.NodeTransformer):
    def __init__(self):
        self.is_module = True
        self.preserve_module_docstring = True

    def visit_Module(self, node: ast.Module) -> ast.Module:
        self.is_module = True
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            module_docstring = node.body[0]
            remaining_body = self.generic_visit_body(node.body[1:])
            node.body = [module_docstring] + remaining_body
        else:
            node.body = self.generic_visit_body(node.body)
        self.is_module = False
        return node

    def generic_visit_body(self, body: list) -> list:
        new_body = []
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                new_body.append(self.visit(node))
            else:
                new_body.append(self.visit(node))
        return new_body

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        return self._process_function_like(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
        return self._process_function_like(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        new_body = self._remove_docstring_from_body(node.body)
        node.body = new_body
        node.decorator_list = [self.visit(dec) for dec in node.decorator_list]
        return node

    def _process_function_like(self, node):
        new_body = self._remove_docstring_from_body(node.body)
        node.body = new_body
        node.decorator_list = [self.visit(dec) for dec in node.decorator_list]
        return node

    def _remove_docstring_from_body(self, body: list) -> list:
        if not body:
            return body
        new_body = []
        if (
            isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body = body[1:]
        for node in body:
            new_body.append(self.visit(node))
        if not new_body:
            new_body = [ast.Pass()]
        return new_body


def remove_docstrings_from_code(source_code: str) -> str | None:
    try:
        tree = ast.parse(source_code)
        transformer = DocstringRemover()
        new_tree = transformer.visit(tree)
        ast.fix_missing_locations(new_tree)
        compile(new_tree, "<transformed>", "exec")
        return ast.unparse(new_tree)
    except SyntaxError as e:
        logger.error(f"Syntax error in transformed code: {e}")
        return None
    except Exception as e:
        logger.error(f"Error processing code: {e}")
        return None


def validate_python_code(code: str) -> bool:
    try:
        ast.parse(code)
        compile(code, "<string>", "exec")
        return True
    except (SyntaxError, ValueError) as e:
        logger.error(f"Code validation failed: {e}")
        return False


def process_file(file_path: Path) -> tuple[Path, bool, str | None]:
    try:
        original_code = file_path.read_text(encoding="utf-8")
        if not validate_python_code(original_code):
            return (file_path, False, "Original code validation failed")
        modified_code = remove_docstrings_from_code(original_code)
        if modified_code is None:
            return (file_path, False, "Docstring removal failed")
        if not validate_python_code(modified_code):
            return (file_path, False, "Modified code validation failed")
        file_path.write_text(modified_code, encoding="utf-8")
        return (file_path, True, None)
    except Exception as e:
        return (file_path, False, str(e))


def find_python_files(paths: list[Path]) -> list[Path]:
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
            sys.exit(1)
    python_files = find_python_files(input_paths)
    if not python_files:
        logger.warning("No Python files found to process")
        sys.exit(0)
    logger.info(f"Found {len(python_files)} Python file(s) to process")
    max_workers = 8
    successful = 0
    failed = 0
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {executor.submit(process_file, file_path): file_path for file_path in python_files}
        for future in as_completed(future_to_file):
            file_path, success, error = future.result()
            if success:
                logger.info(f"✓ Processed: {file_path}")
                successful += 1
            else:
                logger.error(f"✗ Failed: {file_path} - {error}")
                failed += 1
    logger.info(f"\n{'=' * 40}")
    logger.info("Processing complete:")
    logger.info(f"  Successful: {successful}")
    logger.info(f"  Failed:     {failed}")
    logger.info(f"  Total:      {len(python_files)}")
    logger.info(f"{'=' * 40}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    raise SystemExit(main())
