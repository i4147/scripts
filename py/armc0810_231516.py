from __future__ import annotations

import argparse
import ast
import shutil
import sys
import tempfile
import zipfile
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


class CommentRemover:
    def __init__(self, validate: bool = True, remove_docstrings: bool = False):
        self.validate = validate
        self.remove_docstrings = remove_docstrings
        self.total_files = 0
        self.total_comments_removed = 0
        self.failed_files = []
        self.processed_whl_files = []

    @staticmethod
    def is_python_file(path: Path) -> bool:
        if path.suffix == ".py":
            return True
        if path.suffix == "" and path.is_file():
            try:
                with open(path, "rb") as f:
                    first_line = f.readline().decode("utf-8", errors="ignore")
                    return first_line.startswith("#!") and "python" in first_line
            except (OSError, UnicodeDecodeError):
                return False
        return False

    @staticmethod
    def validate_syntax(code: str) -> tuple[bool, str]:
        try:
            ast.parse(code)
            return (True, "")
        except SyntaxError as e:
            return (False, f"Syntax Error at line {e.lineno}: {e.msg}")

    def get_docstring_ranges(self, code: str) -> set[int]:
        if not self.remove_docstrings:
            return set()

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return set()

        docstring_lines = set()

        module_doc_node = None
        if (
            tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)
        ):
            module_doc_node = tree.body[0]

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                if node == module_doc_node:
                    continue

                for ln in range(node.lineno, node.end_lineno + 1):
                    docstring_lines.add(ln)

        return docstring_lines

    @staticmethod
    def should_preserve_comment(line: str, comment_start: int) -> bool:
        comment_text = line[comment_start + 1 :].strip()
        if comment_start == 0 and line.startswith("#!"):
            return True
        if comment_text.startswith("type:"):
            return True
        return bool(comment_text.startswith("fmt:"))

    def remove_comments(self, source_code: str) -> tuple[str, int]:
        doc_ranges = self.get_docstring_ranges(source_code)
        lines = source_code.split("\n")
        cleaned_lines = []
        comment_count = 0
        in_multiline_string = False
        string_delimiter = None

        for _line_index, line in enumerate(lines):
            line_num = _line_index + 1

            if line_num in doc_ranges:
                continue

            for delimiter in ('"""', "'''"):
                if delimiter in line:
                    temp_line = line
                    i = 0
                    count = 0
                    while i < len(temp_line):
                        if temp_line[i : i + 3] == delimiter:
                            count += 1
                            i += 3
                        else:
                            i += 1
                    if count % 2 == 1:
                        if not in_multiline_string:
                            in_multiline_string = True
                            string_delimiter = delimiter
                        elif string_delimiter == delimiter:
                            in_multiline_string = False

            if in_multiline_string:
                cleaned_lines.append(line)
                continue

            cleaned_line = ""
            in_string = False
            string_char = None
            i = 0
            comment_found = False
            while i < len(line):
                char = line[i]
                if char in ('"', "'") and (i == 0 or line[i - 1] != "\\"):
                    if not in_string:
                        in_string = True
                        string_char = char
                    elif char == string_char:
                        in_string = False
                        string_char = None
                if char == "#" and (not in_string):
                    if CommentRemover.should_preserve_comment(line, i):
                        cleaned_line = line
                        comment_found = True
                        break
                    else:
                        comment_found = True
                        break
                cleaned_line += char
                i += 1

            if comment_found:
                cleaned_line = cleaned_line.rstrip()
                if cleaned_line and (not cleaned_line.startswith("#!")):
                    comment_count += 1
            cleaned_lines.append(cleaned_line)

        while cleaned_lines and (not cleaned_lines[-1]):
            cleaned_lines.pop()

        result = "\n".join(cleaned_lines)
        if result and (not result.endswith("\n")):
            result += "\n"
        return (result, comment_count)

    def process_file(self, file_path: Path) -> tuple[Path, int, bool, bool, str]:
        try:
            with open(file_path, encoding="utf-8") as f:
                original_code = f.read()

            cleaned_code, comment_count = self.remove_comments(original_code)
            changed = cleaned_code != original_code

            if self.validate:
                is_valid, error_msg = self.validate_syntax(cleaned_code)
                if not is_valid:
                    return (file_path, 0, False, False, f"Validation failed: {error_msg}")

            if changed:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(cleaned_code)

            return (file_path, comment_count, True, changed, "OK")
        except Exception as e:
            return (file_path, 0, False, False, f"Error: {e!s}")

    def process_whl_file(self, whl_path: Path, dry_run: bool = False) -> tuple[int, list[tuple[str, int]], bool]:
        file_results = []
        total_removed = 0
        success = True
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                with zipfile.ZipFile(whl_path, "r") as zip_ref:
                    zip_ref.extractall(temp_path)

                python_files = [
                    p for p in temp_path.rglob("*") if p.is_file() and (p.suffix == ".py" or self.is_python_file(p))
                ]

                if not python_files:
                    return (0, [], True)

                for file_path in python_files:
                    _, comments_removed, file_success, changed, _ = self.process_file(file_path)
                    if file_success and changed:
                        rel_path = str(file_path.relative_to(temp_path))
                        file_results.append((rel_path, comments_removed))
                        total_removed += comments_removed
                    elif not file_success:
                        success = False

                if not dry_run and total_removed > 0:
                    backup_path = whl_path.with_suffix(".whl.bak")
                    if not backup_path.exists():
                        shutil.copy2(whl_path, backup_path)
                    with zipfile.ZipFile(whl_path, "w", zipfile.ZIP_DEFLATED) as zip_ref:
                        for file_path in temp_path.rglob("*"):
                            if file_path.is_file():
                                arcname = str(file_path.relative_to(temp_path))
                                zip_ref.write(file_path, arcname)
                return (total_removed, file_results, success)
        except zipfile.BadZipFile:
            return (0, [], False)
        except Exception as e:
            print(f"⚠ Error processing wheel {whl_path.name}: {e!s}")
            return (0, [], False)

    def process_files(
        self,
        paths: list[Path],
        max_workers: int = 4,
        dry_run: bool = False,
        process_wheels: bool = False,
        recursive_wheels: bool = False,
    ) -> None:
        print("🔍 Scanning for Python files...")
        python_files = []
        wheel_files = []
        for path in paths:
            if not path.exists():
                print(f"⚠ Warning: Path does not exist: {path}", file=sys.stderr)
                continue
            if path.is_file():
                if self.is_python_file(path):
                    python_files.append(path)
                elif path.suffix == ".whl" and process_wheels:
                    wheel_files.append(path)
            elif path.is_dir():
                python_files.extend(path.rglob("*.py"))
                python_files.extend(
                    [f for f in path.rglob("*") if f.is_file() and f.suffix == "" and self.is_python_file(f)]
                )
                if process_wheels:
                    wheel_files.extend(
                        path.rglob("*.whl")
                        if recursive_wheels
                        else [f for f in path.iterdir() if f.is_file() and f.suffix == ".whl"]
                    )

        self.total_files = len(python_files)
        if python_files:
            print(f"✓ Found {self.total_files} Python file(s)\n")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(self.process_file, file_path): file_path for file_path in python_files}
                for future in as_completed(futures):
                    file_path, comments_removed, success, changed, message = future.result()
                    if success and changed:
                        self.total_comments_removed += comments_removed
                        print(f"✓ {file_path.name:50} | Comments removed: {comments_removed:3}")
                    elif not success:
                        print(f"✗ {file_path.name:50} | {message}")
                        self.failed_files.append((file_path, message))

        if wheel_files:
            print(f"\n📦 Found {len(wheel_files)} wheel file(s)\n")
            for whl_path in wheel_files:
                total_removed, file_results, success = self.process_whl_file(whl_path, dry_run)
                if file_results:
                    self.total_comments_removed += total_removed
                    print(f"✓ {whl_path.name:50} | Removed {total_removed} comments from {len(file_results)} file(s)")
                    self.processed_whl_files.append((whl_path, total_removed, len(file_results)))
                if not success:
                    print(f"  ⚠ Some files in {whl_path.name} had processing errors")

    def print_summary(self) -> None:
        print("\n" + "=" * 80)
        print("📊 SUMMARY")
        print("-" * 42)
        print(f"Comments removed:           {self.total_comments_removed}")
        print(f"Wheel files modified:      {len(self.processed_whl_files)}")
        print(f"Failed files:               {len(self.failed_files)}")
        if self.failed_files:
            print("\n❌ Failed files:")
            for file_path, error in self.failed_files:
                print(f"  • {file_path}: {error}")
        print("-" * 42)


def main():
    parser = argparse.ArgumentParser(
        description="Remove comments from Python files with AST validation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("paths", nargs="*", type=Path, default=[Path.cwd()])
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-validate", action="store_true")
    parser.add_argument(
        "-d", "--remove-docstrings", action="store_true", help="Remove all docstrings except module-level ones"
    )
    parser.add_argument("--wheels", action="store_true")
    parser.add_argument("--recursive-wheels", action="store_true")

    args = parser.parse_args()
    remover = CommentRemover(validate=not args.no_validate, remove_docstrings=args.remove_docstrings)
    try:
        remover.process_files(
            args.paths,
            max_workers=args.workers,
            dry_run=args.dry_run,
            process_wheels=args.wheels,
            recursive_wheels=args.recursive_wheels,
        )
        remover.print_summary()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Fatal error: {e!s}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
