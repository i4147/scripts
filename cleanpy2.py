import argparse
import multiprocessing
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Final
import libcst as cst
from loguru import logger
NUM_WORKERS = 8
PRESERVED_PREFIXES = ("#!", "# fmt:", "# type:")
PRESERVED_SUBSTRINGS = ("# fmt:", "# type:")
class CleanTransformer(cst.CSTTransformer):
    def __init__(self):
        super().__init__()
        self.comments_removed = 0
        self.docstrings_removed = 0
    def leave_Module(self, original_node, updated_node):
        return updated_node
    def leave_FunctionDef(
        self,
        original_node,
        updated_node,
    ):
        return self._strip_docstring(updated_node)
    def leave_ClassDef(
        self,
        original_node,
        updated_node,
    ):
        return self._strip_docstring(updated_node)
    def _strip_docstring(
        self,
        node,
    ):
        body = node.body.body
        if not body:
            return node
        first_stmt = body[0]
        if (
            isinstance(first_stmt, cst.SimpleStatementLine)
            and len(first_stmt.body) == 1
            and isinstance(first_stmt.body[0], cst.Expr)
        ):
            expr_value = first_stmt.body[0].value
            if isinstance(expr_value, (cst.SimpleString, cst.ConcatenatedString)):
                self.docstrings_removed += 1
                remaining = list(body[1:])
                if remaining:
                    new_body = node.body.with_changes(body=remaining)
                else:
                    new_body = node.body.with_changes(
                        body=[cst.SimpleStatementLine(body=[cst.Pass()])]
                    )
                return node.with_changes(body=new_body)
        return node
    def leave_Comment(
        self,
        original_node,
        updated_node,
    ):
        comment_text = original_node.value.strip()
        if comment_text.startswith(PRESERVED_PREFIXES) or any(
            marker in comment_text for marker in PRESERVED_SUBSTRINGS
        ):
            return updated_node
        self.comments_removed += 1
        return cst.RemoveFromParent()
def process_file(path):
    try:
        original_source = path.read_text(encoding="utf-8")
        module = cst.parse_module(original_source)
        transformer = CleanTransformer()
        modified_module = module.visit(transformer)
        new_source = modified_module.code
        if new_source == original_source:
            return path, 0, 0, True
        path.write_text(new_source, encoding="utf-8", newline="\n")
        return (
            path,
            transformer.comments_removed,
            transformer.docstrings_removed,
            True,
        )
    except Exception as exc:  
        logger.error(f"Error processing {path}: {exc}")
        return path, 0, 0, False
def collect_python_files(paths):
    py_files = []
    for raw in paths:
        path = Path(raw).resolve()
        if path.is_file() and path.suffix == ".py":
            py_files.append(path)
        elif path.is_dir():
            py_files.extend(path.rglob("*.py"))
        else:
            logger.warning(f"Skipping non-existent path: {path}")
    return sorted(set(py_files))
def build_arg_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Remove comments & docstrings from Python files "
            "(preserves shebangs, # fmt, # type, module docstrings)"
        )
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to process (default: current directory)",
    )
    return parser
def main():
    parser = build_arg_parser()
    args = parser.parse_args()
    py_files = collect_python_files(args.paths)
    if not py_files:
        print("No Python files found.")
        return 0
    print(f"Found {len(py_files)} Python files to process...")
    total_comments = 0
    total_docstrings = 0
    processed = 0
    with Pool(processes=NUM_WORKERS) as pool:
        async_results = [pool.apply_async(process_file, (f,)) for f in py_files]
        for result in async_results:
            path, comments, docstrings, success = result.get()
            processed += 1
            if not success:
                continue
            total_comments += comments
            total_docstrings += docstrings
            if comments or docstrings:
                logger.success(
                    f"{path.name:<30} removed "
                    f"{comments:>2} comments, {docstrings:>2} docstrings"
                )
            else:
                print(f"{path.name:<30} (no changes)")
    print("=" * 40)
    logger.success("Finished!")
    print(f"Files processed   : {processed}")
    print(f"Comments removed  : {total_comments}")
    print(f"Docstrings removed: {total_docstrings}")
    print("-" * 40)
    return 0
if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
