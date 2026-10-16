from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import libcst as cst


class CleanTransformer(cst.CSTTransformer):
    def __init__(self):
        super().__init__()
        self.comments_removed = 0
        self.docstrings_removed = 0

    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
        return updated_node

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
        return self._strip_docstring(updated_node)

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
        return self._strip_docstring(updated_node)

    def _strip_docstring(self, node):
        if not node.body.body:
            return node
        first_stmt = node.body.body[0]
        if (
            isinstance(first_stmt, cst.SimpleStatementLine)
            and len(first_stmt.body) == 1
            and isinstance(first_stmt.body[0], cst.Expr)
        ):
            expr_value = first_stmt.body[0].value
            if isinstance(expr_value, (cst.SimpleString, cst.ConcatenatedString)):
                self.docstrings_removed += 1
                remaining = list(node.body.body[1:])
                if not remaining:
                    new_body = node.body.with_changes(body=[cst.SimpleStatementLine(body=[cst.Pass()])])
                else:
                    new_body = node.body.with_changes(body=remaining)
                return node.with_changes(body=new_body)
        return node

    def leave_Comment(self, original_node: cst.Comment, updated_node: cst.Comment) -> cst.RemovalSentinel | cst.Comment:
        comment_text = original_node.value.strip()
        if (
            comment_text.startswith(("#!", "# fmt:", "# type:"))
            or "# fmt:" in comment_text
            or "# type:" in comment_text
        ):
            return updated_node
        self.comments_removed += 1
        return cst.RemoveFromParent()


def process_file(file_path: Path) -> tuple[Path, int, int, bool]:
    try:
        original_source = file_path.read_text(encoding="utf-8")
        module = cst.parse_module(original_source)
        transformer = CleanTransformer()
        modified_module = module.visit(transformer)
        new_source = modified_module.code
        if new_source == original_source:
            return file_path, 0, 0, True
        file_path.write_text(new_source, encoding="utf-8", newline="\n")
        return (
            file_path,
            transformer.comments_removed,
            transformer.docstrings_removed,
            True,
        )
    except Exception as e:
        print(f"❌ Error processing {file_path}: {e}")
        return file_path, 0, 0, False


def main():
    parser = argparse.ArgumentParser(
        description="Remove comments & docstrings from Python files (preserves shebangs, # fmt, # type, module docstrings)"
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to process (default: current directory)",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=None,
        help="Number of parallel jobs (default: CPU count)",
    )
    args = parser.parse_args()
    py_files: list[Path] = []
    for p in args.paths:
        path = Path(p).resolve()
        if path.is_file() and path.suffix == ".py":
            py_files.append(path)
        elif path.is_dir():
            py_files.extend(path.rglob("*.py"))
        else:
            print(f"⚠️  Skipping non-existent path: {path}")
    py_files = sorted(set(py_files))
    if not py_files:
        print("No Python files found.")
        return
    print(f"🔍 Found {len(py_files)} Python files to process...\n")
    total_comments = 0
    total_docstrings = 0
    processed = 0
    with ProcessPoolExecutor(max_workers=args.jobs) as executor:
        future_to_file = {executor.submit(process_file, f): f for f in py_files}
        for future in as_completed(future_to_file):
            file_path, comments, docstrings, success = future.result()
            processed += 1
            if success:
                total_comments += comments
                total_docstrings += docstrings
                if comments > 0 or docstrings > 0:
                    print(f"✅ {file_path.name:<30} removed {comments:>2} comments, {docstrings:>2} docstrings")
                else:
                    print(f"✓  {file_path.name:<30} (no changes)")
    print("\n" + "=" * 40)
    print("🎉 Finished!")
    print(f"   Files processed : {processed}")
    print(f"   Comments removed: {total_comments}")
    print(f"   Docstrings removed: {total_docstrings}")
    print("-" * 40)


if __name__ == "__main__":
    raise SystemExit(main())
