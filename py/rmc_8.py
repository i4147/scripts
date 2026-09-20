import argparse
import ast
import shutil
import sys
import tempfile
import zipfile
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path


def get_files(root_dir):
    root_path = Path(root_dir)
    for r, d, files in root_path.walk(top_down=True):
        for f in files:
            filepath = Path(r) / f
            if filepath.is_symlink() or ".git" in filepath.parts:
                continue
            yield filepath


@dataclass
class FileResult:
    path: Path
    comments_removed: int
    docstrings_removed: int
    changed: bool
    error: str | None = None


class DocstringProcessor(ast.NodeTransformer):
    def __init__(self, preserve_module_docstring: bool = True) -> None:
        self.docstrings_removed = 0
        self.preserve_module_docstring = preserve_module_docstring
        super().__init__()

    def _remove_docstring(self, node) -> bool:
        if docstring := ast.get_docstring(node):
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


def extract_shebang_and_encoding(source_code: str) -> tuple[str, str, str]:
    lines = source_code.splitlines(keepends=True)
    shebang = ""
    encoding = ""
    remaining_lines = []
    for i, line in enumerate(lines):
        if i == 0 and line.startswith("#!"):
            shebang = line
            continue
        elif i < 2 and line.startswith(("# -*- coding:", "# coding:")):
            encoding = line
            continue
        remaining_lines.append(line)
    return ("".join(remaining_lines), shebang, encoding)


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
            if char in ('"', "'") and (not in_triple_quotes):
                if i + 2 < len(line) and line[i + 1] == char and (line[i + 2] == char):
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
                if not in_string and (not in_triple_quotes):
                    in_string = True
                    string_char = char
                elif in_string and string_char == char and (not in_triple_quotes):
                    in_string = False
                    string_char = None
                new_line.append(char)
                i += 1
                continue
            if char == "#" and (not in_string) and (not in_triple_quotes):
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
    return ("".join(result_lines), comments_removed)


def validate_python_code(code: str) -> Tuple[bool, str | None]:
    try:
        ast.parse(code)
        return (True, None)
    except SyntaxError as e:
        return (False, f"Syntax error at line {e.lineno}, column {e.offset}: {e.msg}")
    except Exception as e:
        return (False, str(e))


def process_docstrings_ast(source_code: str, preserve_module_docstring: bool = True) -> Tuple[str, int]:
    try:
        tree = ast.parse(source_code)
        processor = DocstringProcessor(preserve_module_docstring)
        modified_tree = processor.visit(tree)
        ast.fix_missing_locations(modified_tree)
        modified_code = ast.unparse(modified_tree)
        return (modified_code, processor.docstrings_removed)
    except SyntaxError:
        return (source_code, 0)


def is_python_file(path: Path) -> bool:
    if path.suffix.lower() in (".py", ".pyw", ".pyi"):
        return True
    if not path.suffix:
        try:
            with open(path, "r", encoding="utf-8") as f:
                first_line = f.readline()
                return first_line.startswith("#!") and "python" in first_line.lower()
        except (IOError, UnicodeDecodeError):
            return False
    return False


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
            is_valid, error_msg = validate_python_code(final_code)
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


def process_dry_run_placeholder(path: Path, preserve_module_docstring: bool) -> FileResult:
    return FileResult(path, 0, 0, False, "dry run")


def process_wheel_file(
    whl_path: Path, preserve_module_docstring: bool = True, dry_run: bool = False
) -> list[FileResult]:
    results = []
    temp_dir = None
    try:
        temp_dir = Path(tempfile.mkdtemp(prefix="whl_processing_"))
        extract_dir = temp_dir / "extracted"
        extract_dir.mkdir()
        with zipfile.ZipFile(whl_path, "r") as whl:
            whl.extractall(extract_dir)
        python_files = [f for f in extract_dir.rglob("*") if f.is_file() and is_python_file(f)]
        for py_file in python_files:
            if not dry_run:
                result = process_python_file(py_file, preserve_module_docstring)
            else:
                result = FileResult(py_file, 0, 0, False, None)
            relative_path = py_file.relative_to(extract_dir)
            result.path = Path(f"{whl_path.name}::{relative_path}")
            results.append(result)
        if not dry_run and any((r.changed for r in results)):
            new_whl_path = whl_path.with_suffix(".tmp.whl")
            with zipfile.ZipFile(new_whl_path, "w", zipfile.ZIP_DEFLATED) as new_whl:
                for file_path in extract_dir.rglob("*"):
                    if file_path.is_file():
                        arcname = file_path.relative_to(extract_dir)
                        new_whl.write(file_path, arcname)
            shutil.move(str(new_whl_path), str(whl_path))
    except zipfile.BadZipFile:
        results.append(
            FileResult(
                path=whl_path,
                comments_removed=0,
                docstrings_removed=0,
                changed=False,
                error="Invalid or corrupted wheel file",
            )
        )
    except Exception as e:
        results.append(FileResult(path=whl_path, comments_removed=0, docstrings_removed=0, changed=False, error=str(e)))
    finally:
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
    return results


def format_result(result: FileResult, cwd: Path) -> str:
    try:
        display_path = result.path.relative_to(cwd)
    except ValueError:
        display_path = result.path
    if result.error:
        return f"{display_path} (error: {result.error})"
    if not result.changed:
        return f"{display_path} (no change)"
    parts = []
    if result.comments_removed > 0:
        parts.append(f"{result.comments_removed} comment{('s' if result.comments_removed != 1 else '')}")
    if result.docstrings_removed > 0:
        parts.append(f"{result.docstrings_removed} docstring{('s' if result.docstrings_removed != 1 else '')}")
    return f"{display_path} ({', '.join(parts)} removed)"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove comments and docstrings from Python files (preserves formatting)"
    )
    parser.add_argument("target", nargs="?", default=".", help="Target file or directory (default: current directory)")
    parser.add_argument("--workers", type=int, default=4, help="Number of worker processes (default: 4)")
    parser.add_argument("--remove-module-docstring", action="store_true", help="Also remove module-level docstrings")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without modifying files")
    args = parser.parse_args()
    cwd = Path.cwd()
    target_path = Path(args.target).resolve()
    if not target_path.exists():
        print(f"Error: {target_path} does not exist")
        sys.exit(1)
    wheel_files = []
    regular_files = []
    for p in get_files(target_path):
        if p.suffix.lower() == ".whl":
            wheel_files.append(p)
        elif p.suffix == ".py":
            regular_files.append(p)
    if not wheel_files and (not regular_files):
        print("No Python files or wheel files found")
        return
    print(
        f"Found: {len(regular_files)} Python file{('s' if len(regular_files) != 1 else '')}, {len(wheel_files)} wheel file{('s' if len(wheel_files) != 1 else '')}"
    )
    if args.dry_run:
        print("DRY RUN - No files will be modified")
    total_files = 0
    changed_files = 0
    total_comments = 0
    total_docstrings = 0
    errors = 0
    preserve_module_docstring = not args.remove_module_docstring
    if regular_files:
        func = process_dry_run_placeholder if args.dry_run else process_python_file
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            future_to_file = {executor.submit(func, path, preserve_module_docstring): path for path in regular_files}
            for future in as_completed(future_to_file):
                result = future.result()
                total_files += 1
                if result.changed:
                    changed_files += 1
                total_comments += result.comments_removed
                docstrings_removed = result.docstrings_removed if result.docstrings_removed is not None else 0
                total_docstrings += docstrings_removed
                if result.error and result.error != "dry run":
                    errors += 1
                if not args.dry_run:
                    print(format_result(result, cwd))
                else:
                    try:
                        r_path = result.path.relative_to(cwd)
                    except ValueError:
                        r_path = result.path
                    print(f"{r_path} (would process)")
    for wheel_path in wheel_files:
        try:
            w_path_display = wheel_path.relative_to(cwd)
        except ValueError:
            w_path_display = wheel_path
        print(f"\nProcessing wheel file: {w_path_display}")
        wheel_results = process_wheel_file(wheel_path, preserve_module_docstring, args.dry_run)
        if args.dry_run:
            print(f"  Would process {len(wheel_results)} files inside {w_path_display}")
        else:
            for result in wheel_results:
                total_files += 1
                if result.changed:
                    changed_files += 1
                total_comments += result.comments_removed
                total_docstrings += result.docstrings_removed
                if result.error:
                    errors += 1
                print(f"  {format_result(result, cwd)}")
    if not args.dry_run and total_files > 0:
        print(f"\n{'=' * 50}\nSummary:")
        print(f"  Total files processed: {total_files}")
        print(f"  Files changed: {changed_files}")
        print(f"  Total comments removed: {total_comments}")
        print(f"  Total docstrings removed: {total_docstrings}")
        if errors > 0:
            print(f"  Errors: {errors}")


if __name__ == "__main__":
    main()
