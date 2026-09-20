import ast
import shutil
from collections.abc import Sequence
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final
import libcst as cst
from dh import get_pyfiles  
from loguru import logger
MAX_WORKERS = 8
class StripTransformer(cst.CSTTransformer):
    def leave_Comment(self, original_node, updated_node):
        return cst.RemovalSentinel.REMOVE
    @staticmethod
    def _strip_leading_docstring(
        body,
    ):
        if not body:
            return tuple(body)
        first = body[0]
        if (
            isinstance(first, cst.SimpleStatementLine)
            and len(first.body) == 1
            and isinstance(first.body[0], cst.Expr)
            and isinstance(first.body[0].value, cst.SimpleString)
        ):
            return tuple(body[1:])
        return tuple(body)
    def _strip_suite(self, suite):
        if isinstance(suite, cst.IndentedBlock):
            new_body = self._strip_leading_docstring(suite.body)
            if not new_body:
                new_body = (cst.SimpleStatementLine(body=[cst.Pass()]),)
            return suite.with_changes(body=new_body)
        if isinstance(suite, cst.SimpleStatementSuite):
            new_body = self._strip_leading_docstring(suite.body)
            if not new_body:
                new_body = (cst.Pass(),)
            return suite.with_changes(body=new_body)
        return suite
    def leave_Module(self, original_node, updated_node):
        new_body = self._strip_leading_docstring(updated_node.body)
        return updated_node.with_changes(body=new_body)
    def leave_FunctionDef(self, original_node, updated_node):
        return updated_node.with_changes(body=self._strip_suite(updated_node.body))
    def leave_ClassDef(self, original_node, updated_node):
        return updated_node.with_changes(body=self._strip_suite(updated_node.body))
def strip_comments_and_docstrings(file_path_str):
    file_path = Path(file_path_str)
    backup_path = file_path.with_suffix(file_path.suffix + ".bak")
    try:
        original_content = file_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.error(f"Error reading file {file_path}: {exc}")
        return False
    try:
        ast.parse(original_content, filename=str(file_path))
    except SyntaxError as exc:
        logger.warning(
            f"Original code has syntax error: {file_path} - {exc}. Skipping."
        )
        return False
    try:
        module = cst.parse_module(original_content)
    except cst.ParserSyntaxError as exc:
        logger.warning(f"libcst failed to parse {file_path}: {exc}. Skipping.")
        return False
    transformer = StripTransformer()
    new_module = module.visit(transformer)
    final_code = new_module.code
    if final_code == original_content:
        print(f"No comments or docstrings to strip in {file_path}")
        return False
    try:
        ast.parse(final_code, filename=str(file_path))
    except SyntaxError as exc:
        logger.warning(
            f"Syntax error after stripping comments/docstrings from {file_path}. "
            f"Reverting. ({exc})"
        )
        return False
    try:
        shutil.copy2(file_path, backup_path)
        print(f"Backup created: {backup_path}")
    except Exception as exc:
        logger.error(f"Error creating backup for {file_path}: {exc}")
        return False
    try:
        file_path.write_text(final_code, encoding="utf-8")
        print(f"Successfully stripped comments/docstrings from {file_path}")
        return True
    except Exception as exc:
        logger.error(f"Error writing cleaned file {file_path}: {exc}")
        try:
            shutil.move(str(backup_path), str(file_path))
            print(f"Restored original content from backup for {file_path}")
        except Exception as restore_exc:
            logger.critical(
                f"Failed to write cleaned file and restore backup for {file_path}: "
                f"{restore_exc}"
            )
        return False
def process_directory(directory):
    python_files = list(get_pyfiles(directory))
    print(f"Found {len(python_files)} Python files to process.")
    if not python_files:
        print("Nothing to do.")
        return
    processed_count = 0
    ordered = sorted(python_files)
    with Pool(processes=MAX_WORKERS) as pool:
        async_results = [
            pool.apply_async(strip_comments_and_docstrings, (str(file_path),))
            for file_path in ordered
        ]
        for file_path, async_res in zip(ordered, async_results):
            try:
                if async_res.get():
                    processed_count += 1
            except Exception as exc:
                logger.error(f"Error processing future for {file_path}: {exc}")
    print(
        f"Finished processing. Successfully stripped comments/docstrings from "
        f"{processed_count}/{len(python_files)} files."
    )
def main():
    target_directory = "."
    print(
        f"Starting comment and docstring stripping in directory: "
        f"{Path(target_directory).resolve()}"
    )
    process_directory(target_directory)
if __name__ == "__main__":
    raise SystemExit(main())
