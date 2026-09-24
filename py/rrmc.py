from __future__ import annotations

import argparse
import ast
import io
import tokenize
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from loguru import logger

SKIP_DIRS = {".git", "__pycache__", ".ruff_cache", ".pytest_cache"}


class PythonCleaner(ast.NodeTransformer):
    def __init__(self):
        self.docstrings_removed = 0

    def _handle_docstring(self, node):
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            self.docstrings_removed += 1
            if len(node.body) == 1 and not isinstance(node, ast.Module):
                node.body[0] = ast.Pass()
            else:
                node.body.pop(0)
        return node

    def visit_Module(self, node):
        self._handle_docstring(node)
        return self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self._handle_docstring(node)
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self._handle_docstring(node)
        return self.generic_visit(node)

    def visit_ClassDef(self, node):
        self._handle_docstring(node)
        return self.generic_visit(node)


def count_comments(source: str) -> int:
    count = 0
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            if tok.type == tokenize.COMMENT:
                count += 1
    except Exception:
        pass
    return count


def is_python_script(path: Path) -> bool:
    if path.suffix == ".py":
        return True
    try:
        with path.open("r") as f:
            first_line = f.readline()
            return first_line.startswith("#!") and "python" in first_line.lower()
    except Exception:
        return False


def process_file(args):
    path, root = args
    try:
        rel_path = path.relative_to(root)
        source = path.read_text()
        comment_count = count_comments(source)
        tree = ast.parse(source)
        cleaner = PythonCleaner()
        modified_tree = cleaner.visit(tree)
        ast.fix_missing_locations(modified_tree)
        cleaned_code = ast.unparse(modified_tree)
        ast.parse(cleaned_code)
        doc_count = cleaner.docstrings_removed
        if comment_count > 0 or doc_count > 0:
            path.write_text(cleaned_code)
            logger.info(f"{rel_path}: removed {comment_count} comments, {doc_count} docstrings")
            return comment_count + doc_count
        return 0
    except Exception as e:
        logger.error(f"Failed {path}: {e}")
        return 0


def main():
    parser = argparse.ArgumentParser()
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
    with ProcessPoolExecutor() as executor:
        results = list(executor.map(process_file, files_to_process))
    total_removed = sum(results)
    logger.success(f"Cleanup complete. Total elements removed: {total_removed}")


if __name__ == "__main__":
    raise SystemExit(main())
