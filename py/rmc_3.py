import argparse
import ast
import shutil
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple


@dataclass
class FileResult:
    path: Path
    comments_removed: int
    docstrings_removed: int
    changed: bool
    error: Optional[str] = None


class DocstringProcessor(ast.NodeTransformer):
    def __init__(self, preserve_module_docstring: bool = True) -> None:
        self.docstrings_removed = 0
        self.preserve_module_docstring = preserve_module_docstring
        super().__init__()

    def _remove_docstring(self, node) -> bool:
        docstring = ast.get_docstring(node)
        if docstring:
            is_module = isinstance(node, ast.Module)
            if is_module and self.preserve_module_docstring:
                return False
            if node.body and isinstance(node.body[0], ast.Expr):
                node.body.pop(0)
                self.docstrings_removed += 1
                if not node.body:
                    node.body.append(ast.Pass())
                return True
        return False

    def visit_FunctionDef(self, node):
        self._remove_docstring(node)
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node):
        self._remove_docstring(node)
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node):
        self._remove_docstring(node)
        self.generic_visit(node)
        return node

    def visit_Module(self, node):
        self._remove_docstring(node)
        self.generic_visit(node)
        return node


def extract_shebang_and_encoding(source_code: str) -> Tuple[str, str, str]:
    lines = source_code.splitlines(keepends=True)
    shebang = ""
    encoding = ""
    remaining_lines = []
    for i, line in enumerate(lines):
        if i == 0 and line.startswith("#!"):
            shebang = line
            continue
        elif i < 2 and line.startswith("# -*- coding:"):
            encoding = line
            continue
        elif i < 2 and line.startswith("# coding:"):
            encoding = line
            continue
        remaining_lines.append(line)
    return "".join(remaining_lines), shebang, encoding


def restore_shebang_and_encoding(code: str, shebang: str, encoding: str) -> str:
    result = []
    if shebang:
        result.append(shebang)
    if encoding:
        result.append(encoding)
    if result:
        result.append("")
    result.append(code)
    return "\n".join(result)


def remove_comments_preserve_format(source_code: str) -> Tuple[str, int]:
    lines = source_code.splitlines(keepends=True)
    comments_removed = 0
    result_lines = []
    in_string = False
    string_char = None
    in_triple_quotes = False
    triple_quote_char = None
    for line in lines:
        new_line = []
        i = 0
        line_has_comment = False
        comment_start = -1
        while i < len(line):
            char = line[i]
            if char in ('"', "'") and not in_triple_quotes:
                if i + 2 < len(line) and line[i + 1] == char and line[i + 2] == char:
                    if not in_string:
                        in_triple_quotes = True
                        triple_quote_char = char
                        new_line.append(char * 3)
                        i += 3
                        continue
                    elif in_triple_quotes and triple_quote_char == char:
                        in_triple_quotes = False
                        triple_quote_char = None
                        new_line.append(char * 3)
                        i += 3
                        continue
                if not in_string and not in_triple_quotes:
                    in_string = True
                    string_char = char
                elif in_string and string_char == char and not in_triple_quotes:
                    in_string = False
                    string_char = None
                new_line.append(char)
                i += 1
                continue
            if char == "#" and not in_string and not in_triple_quotes:
                remaining = line[i:]
                if remaining.startswith("# type:"):
                    new_line.append(remaining)
                    break
                line_has_comment = True
                comment_start = i
                break
            new_line.append(char)
            i += 1
        if line_has_comment and comment_start >= 0:
            comments_removed += 1
            result_line = "".join(new_line)
            result_lines.append(result_line.rstrip() + "\n")
        else:
            result_lines.append("".join(new_line))
    return "".join(result_lines), comments_removed


def validate_python_code(code: str, path: Path) -> Tuple[bool, Optional[str]]:
    try:
        ast.parse(code)
        return True, None
    except SyntaxError as e:
        return (False, f"Syntax error at line {e.lineno}, column {e.offset}: {e.msg}")
    except Exception as e:
        return False, str(e)


def process_docstrings_ast(source_code: str, preserve_module_docstring: bool = True) -> Tuple[str, int]:
    try:
        tree = ast.parse(source_code)
        processor = DocstringProcessor(preserve_module_docstring)
        modified_tree = processor.visit(tree)
        ast.fix_missing_locations(modified_tree)
        modified_code = ast.unparse(modified_tree)
        return modified_code, processor.docstrings_removed
    except SyntaxError as e:
        print(f"Warning: AST parsing error - {e}")
        return source_code, 0


def process_python_file(path: Path, preserve_module_docstring: bool = True) -> FileResult:
    temp_file = None
    try:
        orig = path.read_text(encoding="utf-8")
        code_without_header, shebang, encoding = extract_shebang_and_encoding(orig)
        code_no_comments, comments_removed = remove_comments_preserve_format(code_without_header)
        code_no_docstrings, docstrings_removed = process_docstrings_ast(code_no_comments, preserve_module_docstring)
        final_code = restore_shebang_and_encoding(code_no_docstrings, shebang, encoding)
        changed = comments_removed > 0 or docstrings_removed > 0
        if changed:
            is_valid, error_msg = validate_python_code(final_code, path)
            if not is_valid:
                return FileResult(
                    path=path,
                    comments_removed=0,
                    docstrings_removed=0,
                    changed=False,
                    error=f"Validation failed: {error_msg}",
                )
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, prefix=".tmp_", delete=False
            ) as tmp:
                tmp.write(final_code)
                temp_file = Path(tmp.name)
            shutil.move(str(temp_file), str(path))
        return FileResult(
            path=path, comments_removed=comments_removed, docstrings_removed=docstrings_removed, changed=changed
        )
    except Exception as e:
        if temp_file and temp_file.exists():
            temp_file.unlink()
        return FileResult(path=path, comments_removed=0, docstrings_removed=0, changed=False, error=str(e))


def find_python_files(path: Path) -> list[Path]:
    if path.is_file():
        if path.suffix == ".py":
            return [path]
        return []
    return list(path.rglob("*.py"))


def format_result(result: FileResult) -> str:
    if result.error:
        return f"{result.path.name} (error: {result.error})"
    if not result.changed:
        return f"{result.path.name} (no change)"
    parts = []
    if result.comments_removed > 0:
        parts.append(f"{result.comments_removed} comment{'s' if result.comments_removed != 1 else ''}")
    if result.docstrings_removed > 0:
        parts.append(f"{result.docstrings_removed} docstring{'s' if result.docstrings_removed != 1 else ''}")
    removal_text = ", ".join(parts)
    return f"{result.path.name} ({removal_text} removed)"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove comments and docstrings from Python files (preserves formatting)"
    )
    parser.add_argument("target", nargs="?", default=".", help="Target file or directory (default: current directory)")
    parser.add_argument("--workers", type=int, default=4, help="Number of worker processes (default: 4)")
    parser.add_argument(
        "--remove-module-docstring",
        action="store_true",
        help="Also remove module-level docstrings (preserved by default)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be changed without actually modifying files"
    )
    args = parser.parse_args()
    target_path = Path(args.target).resolve()
    if not target_path.exists():
        print(f"Error: {target_path} does not exist")
        sys.exit(1)
    python_files = find_python_files(target_path)
    if not python_files:
        print("No Python files found")
        return
    print(f"{len(python_files)} file{'s' if len(python_files) != 1 else ''} found")
    if args.dry_run:
        print("DRY RUN - No files will be modified")
    results = []
    preserve_module_docstring = not args.remove_module_docstring
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        future_to_file = {
            executor.submit(
                process_python_file if not args.dry_run else lambda p: FileResult(p, 0, 0, False, "dry run"),
                path,
                preserve_module_docstring,
            ): path
            for path in python_files
        }
        for future in as_completed(future_to_file):
            result = future.result()
            results.append(result)
            if not args.dry_run:
                print(format_result(result))
            else:
                print(f"{result.path.name} (would process)")
    if not args.dry_run:
        total_files = len(results)
        changed_files = sum(1 for r in results if r.changed)
        total_comments = sum(r.comments_removed for r in results)
        total_docstrings = sum(r.docstrings_removed for r in results)
        errors = sum(1 for r in results if r.error)
        print(f"\n{'=' * 50}")
        print(f"Summary:")
        print(f"  Total files processed: {total_files}")
        print(f"  Files changed: {changed_files}")
        print(f"  Total comments removed: {total_comments}")
        print(f"  Total docstrings removed: {total_docstrings}")
        if errors > 0:
            print(f"  Errors: {errors}")


if __name__ == "__main__":
    main()
