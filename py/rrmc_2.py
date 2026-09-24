import argparse
import ast
from collections.abc import Sequence
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final
import libcst as cst
from loguru import logger

SKIP_DIRS = frozenset({".git", "__pycache__", ".ruff_cache", ".pytest_cache"})
MAX_WORKERS = 8
Task = tuple[Path, Path]


def _is_docstring_statement(stmt):
    if not isinstance(stmt, cst.SimpleStatementLine):
        return False
    if len(stmt.body) != 1:
        return False
    expr = stmt.body[0]
    if not isinstance(expr, cst.Expr):
        return False
    value = expr.value
    if not isinstance(value, cst.SimpleString):
        return False
    return "b" not in value.prefix.lower()


def _is_docstring_small_statement(stmt):
    if not isinstance(stmt, cst.Expr):
        return False
    value = stmt.value
    if not isinstance(value, cst.SimpleString):
        return False
    return "b" not in value.prefix.lower()


class PythonCleaner(cst.CSTTransformer):
    def __init__(self):
        super().__init__()
        self.comments_removed = 0
        self.docstrings_removed = 0

    def leave_Comment(
        self,
        original_node,
        updated_node,
    ):
        self.comments_removed += 1
        return cst.RemovalSentinel.REMOVE

    def _strip_statements(self, body):
        if not body:
            return tuple(body)
        if _is_docstring_statement(body[0]):
            self.docstrings_removed += 1
            return tuple(body[1:])
        return tuple(body)

    def _strip_suite(self, suite):
        if isinstance(suite, cst.IndentedBlock):
            new_body = self._strip_statements(suite.body)
            if not new_body:
                new_body = (cst.SimpleStatementLine(body=[cst.Pass()]),)
            return suite.with_changes(body=new_body)
        if isinstance(suite, cst.SimpleStatementSuite):
            small_body = tuple(suite.body)
            if small_body and _is_docstring_small_statement(small_body[0]):
                self.docstrings_removed += 1
                small_body = small_body[1:]
            if not small_body:
                small_body = (cst.Pass(),)
            return suite.with_changes(body=small_body)
        return suite

    def leave_Module(self, original_node, updated_node):
        new_body = self._strip_statements(updated_node.body)
        return updated_node.with_changes(body=new_body)

    def leave_FunctionDef(self, original_node, updated_node):
        return updated_node.with_changes(body=self._strip_suite(updated_node.body))

    def leave_ClassDef(self, original_node, updated_node):
        return updated_node.with_changes(body=self._strip_suite(updated_node.body))


def is_python_script(path):
    if path.suffix == ".py":
        return True
    try:
        with path.open("r", encoding="utf-8") as f:
            first_line = f.readline()
        return first_line.startswith("#!") and "python" in first_line.lower()
    except Exception:
        return False


def process_file(task):
    path, root = task
    try:
        rel_path = path.relative_to(root)
        source = path.read_text(encoding="utf-8")
        module = cst.parse_module(source)
        cleaner = PythonCleaner()
        modified_module = module.visit(cleaner)
        cleaned_code = modified_module.code
        if cleaner.comments_removed == 0 and cleaner.docstrings_removed == 0:
            return 0
        ast.parse(cleaned_code)
        path.write_text(cleaned_code, encoding="utf-8")
        print(f"{rel_path}: removed {cleaner.comments_removed} comments, {cleaner.docstrings_removed} docstrings")
        return cleaner.comments_removed + cleaner.docstrings_removed
    except Exception as exc:
        logger.error(f"Failed {path}: {exc}")
        return 0


def main():
    parser = argparse.ArgumentParser(description="Strip comments and docstrings from Python files using libcst.")
    parser.add_argument("targets", nargs="*", type=str)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    targets = [Path(t).resolve() for t in args.targets] if args.targets else [root]
    files_to_process = []
    for target in targets:
        if target.is_file():
            if not any(part in SKIP_DIRS for part in target.parts) and is_python_script(target):
                files_to_process.append((target, root))
        elif target.is_dir():
            for path in target.rglob("*"):
                if path.is_file() and not any(part in SKIP_DIRS for part in path.parts):
                    if is_python_script(path):
                        files_to_process.append((path.resolve(), root))
    if not files_to_process:
        print("No Python files found to process.")
        return
    total_removed = 0
    with Pool(processes=MAX_WORKERS) as pool:
        async_results = [pool.apply_async(process_file, (task,)) for task in files_to_process]
        for async_res in async_results:
            try:
                total_removed += async_res.get()
            except Exception as exc:
                logger.error(f"Worker raised: {exc}")
    logger.success(f"Cleanup complete. Total elements removed: {total_removed}")


if __name__ == "__main__":
    raise SystemExit(main())
