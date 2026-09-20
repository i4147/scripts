from __future__ import annotations

import ast
import os
import re
import shutil
import sys
import tempfile
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = frozenset(
    {
        ".git",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".venv",
        "venv",
        "lazy",
        ".env",
        "node_modules",
    }
)


@dataclass
class FileResult:
    path: str
    is_error: bool = False
    error_message: str = ""
    comments_removed: int = 0
    docstrings_removed: int = 0
    is_wheel_member: bool = False


@dataclass
class ProcessingStats:
    total_files: int = 0
    changed_files: int = 0
    comments_removed: int = 0
    docstrings_removed: int = 0
    errors: int = 0
    results: list[FileResult] = field(default_factory=list)


class CommentRemover:
    def __init__(self, source: str):
        self.source = source
        self.lines = source.split("\n")
        self.comments_removed = 0

    def remove_comments(self) -> str:
        result_lines = []
        for line in self.lines:
            processed_line, removed = self._process_line(line)
            result_lines.append(processed_line)
            self.comments_removed += removed
        return "\n".join(result_lines)

    def _process_line(self, line: str) -> tuple[str, int]:
        if self._is_shebang(line):
            return (line, 0)
        if self._is_encoding_declaration(line):
            return (line, 0)
        if self._is_type_comment(line):
            return (line, 0)
        processed = self._strip_inline_comment(line)
        removed = 1 if processed != line and processed.strip() else 0
        if removed and (not processed.strip()):
            return ("", 1)
        return (processed, removed)

    @staticmethod
    def _is_shebang(line: str) -> bool:
        return line.startswith("#!")

    @staticmethod
    def _is_encoding_declaration(line: str) -> bool:
        return re.match("#.*?coding[:=]\\s*([-\\w.]+)", line) is not None

    @staticmethod
    def _is_type_comment(line: str) -> bool:
        return "# type:" in line or "# noqa" in line or "# pragma" in line or ("# pylint" in line)

    @staticmethod
    def _strip_inline_comment(line: str) -> str:
        result = []
        i = 0
        in_string = False
        string_char = None
        in_triple = False
        while i < len(line):
            if i + 2 < len(line):
                triple = line[i : i + 3]
                if triple in ('"""', "'''"):
                    if in_triple and string_char == triple:
                        in_triple = False
                        result.append(triple)
                        i += 3
                        continue
                    elif not in_string and (not in_triple):
                        in_triple = True
                        string_char = triple
                        result.append(triple)
                        i += 3
                        continue
            char = line[i]
            if char in ('"', "'") and (not in_triple):
                if in_string and string_char == char:
                    if i > 0 and line[i - 1] != "\\":
                        in_string = False
                        string_char = None
                elif not in_string:
                    in_string = True
                    string_char = char
                result.append(char)
                i += 1
                continue
            if char == "#" and (not in_string) and (not in_triple):
                break
            result.append(char)
            i += 1
        return "".join(result).rstrip()


class DocstringRemover(ast.NodeTransformer):
    def __init__(self, remove_module_docstring: bool = False):
        self.remove_module_docstring = remove_module_docstring
        self.docstrings_removed = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        if (
            self._has_docstring(node)
            and (not self.remove_module_docstring or not self._is_module_level(node))
            and (
                isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            )
        ):
            self.docstrings_removed += 1
            node.body = node.body[1:]
            if not node.body:
                node.body = [ast.Pass()]
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
        if (
            self._has_docstring(node)
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            self.docstrings_removed += 1
            node.body = node.body[1:]
            if not node.body:
                node.body = [ast.Pass()]
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        if (
            self._has_docstring(node)
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            self.docstrings_removed += 1
            node.body = node.body[1:]
            if not node.body:
                node.body = [ast.Pass()]
        self.generic_visit(node)
        return node

    def visit_Module(self, node: ast.Module) -> ast.Module:
        if (
            self.remove_module_docstring
            and self._has_docstring(node)
            and (
                isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            )
        ):
            self.docstrings_removed += 1
            node.body = node.body[1:]
        self.generic_visit(node)
        return node

    @staticmethod
    def _has_docstring(node) -> bool:
        return (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        )

    @staticmethod
    def _is_module_level(node) -> bool:
        return False


def process_single_file(filepath: Path, remove_module_docstring: bool = False, dry_run: bool = False) -> FileResult:
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            original_source = f.read()
        comment_remover = CommentRemover(original_source)
        no_comments = comment_remover.remove_comments()
        try:
            tree = ast.parse(no_comments)
        except SyntaxError as e:
            return FileResult(path=str(filepath), is_error=True, error_message=f"Syntax error: {e}")
        remover = DocstringRemover(remove_module_docstring=remove_module_docstring)
        new_tree = remover.visit(tree)
        ast.fix_missing_locations(new_tree)
        processed_source = ast.unparse(new_tree)
        try:
            ast.parse(processed_source)
        except SyntaxError as e:
            return FileResult(
                path=str(filepath),
                is_error=True,
                error_message=f"Validation error: {e}",
            )
        if processed_source != original_source and (not dry_run):
            try:
                temp_fd, temp_path = tempfile.mkstemp(dir=filepath.parent, prefix=".tmp.", suffix=".py")
                try:
                    with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                        f.write(processed_source)
                    shutil.move(temp_path, filepath)
                except Exception:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
                    raise
            except Exception as e:
                return FileResult(path=str(filepath), is_error=True, error_message=f"Write error: {e}")
        return FileResult(
            path=str(filepath),
            comments_removed=comment_remover.comments_removed,
            docstrings_removed=remover.docstrings_removed,
        )
    except Exception as e:
        return FileResult(path=str(filepath), is_error=True, error_message=str(e))


def process_wheel_file(
    wheel_path: Path, remove_module_docstring: bool = False, dry_run: bool = False
) -> list[FileResult]:
    results = []
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        wheel_name = wheel_path.name
        try:
            with zipfile.ZipFile(wheel_path, "r") as whl:
                whl.extractall(temp_path)
            any_changed = False
            for py_file in temp_path.rglob("*.py"):
                result = process_single_file(py_file, remove_module_docstring, dry_run=True)
                if result.comments_removed > 0 or result.docstrings_removed > 0:
                    result = process_single_file(py_file, remove_module_docstring, dry_run=dry_run)
                    any_changed = True
                relative = py_file.relative_to(temp_path)
                result.path = f"{wheel_name}::{relative}"
                result.is_wheel_member = True
                results.append(result)
            if any_changed and (not dry_run):
                temp_wheel = temp_path / f"{wheel_name}.tmp"
                with zipfile.ZipFile(temp_wheel, "w", zipfile.ZIP_DEFLATED) as whl:
                    for file_path in temp_path.rglob("*"):
                        if file_path.is_file():
                            relative = file_path.relative_to(temp_path)
                            whl.write(file_path, arcname=str(relative))
                shutil.move(str(temp_wheel), str(wheel_path))
        except Exception as e:
            results.append(
                FileResult(
                    path=wheel_name,
                    is_error=True,
                    error_message=f"Wheel processing error: {e}",
                )
            )
    return results


def _worker_process_file(args: tuple[Path, bool, bool]) -> FileResult:
    filepath, remove_module_docstring, dry_run = args
    return process_single_file(filepath, remove_module_docstring, dry_run)


def discover_files(start_path: str) -> tuple[list[Path], list[Path]]:
    start = Path(start_path).resolve()
    if not start.exists():
        print(f"Error: Path not found: {start}", file=sys.stderr)
        return ([], [])
    python_files = []
    wheel_files = []
    if start.is_file():
        if start.suffix == ".py":
            python_files.append(start)
        elif start.suffix == ".whl":
            wheel_files.append(start)
        return (python_files, wheel_files)
    for root, dirs, files in start.walk(top_down=True):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        root_path = Path(root)
        for filename in files:
            filepath = root_path / filename
            if filepath.suffix == ".py":
                python_files.append(filepath)
            elif filepath.suffix == ".whl":
                wheel_files.append(filepath)
    return (python_files, wheel_files)


def print_header(python_count: int, wheel_count: int):
    print(f"\nFound: {python_count} Python files, {wheel_count} wheel files\n")


def print_results(stats: ProcessingStats, base_dir: Path):
    results = sorted(stats.results, key=lambda r: r.path)
    for result in results:
        if result.is_error:
            print(f"✗ {result.path}")
            print(f"  Error: {result.error_message}")
        elif result.comments_removed == 0 and result.docstrings_removed == 0:
            print(f"○ {result.path} (no change)")
        else:
            changes = []
            if result.comments_removed > 0:
                changes.append(f"{result.comments_removed} comment{('s' if result.comments_removed != 1 else '')}")
            if result.docstrings_removed > 0:
                changes.append(
                    f"{result.docstrings_removed} docstring{('s' if result.docstrings_removed != 1 else '')}"
                )
            print(f"✓ {result.path} ({', '.join(changes)} removed)")


def print_summary(stats: ProcessingStats):
    print("\n" + "=" * 40)
    print("Summary:")
    print(f"  Total files processed: {stats.total_files}")
    print(f"  Files changed: {stats.changed_files}")
    print(f"  Total comments removed: {stats.comments_removed}")
    print(f"  Total docstrings removed: {stats.docstrings_removed}")
    if stats.errors > 0:
        print(f"  Errors: {stats.errors}")
    print("=" * 40 + "\n")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Strip comments and docstrings from Python source files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\nExamples:\n\n  python strip_comments.py\n\n\n  python strip_comments.py src/main.py\n\n\n  python strip_comments.py --remove-module-docstring\n\n\n  python strip_comments.py --dry-run\n\n\n  python strip_comments.py --workers 16\n        ",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="File or directory to process (default: current directory)",
    )
    parser.add_argument(
        "--remove-module-docstring",
        action="store_true",
        help="Also strip module-level docstrings (preserved by default)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without modifying files",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel worker processes (default: 4)",
    )
    args = parser.parse_args()
    python_files, wheel_files = discover_files(args.path)
    if not python_files and (not wheel_files):
        print("No Python files found", file=sys.stderr)
        return 1
    print_header(len(python_files), len(wheel_files))
    stats = ProcessingStats(total_files=len(python_files) + len(wheel_files))
    for wheel_file in wheel_files:
        results = process_wheel_file(
            wheel_file,
            remove_module_docstring=args.remove_module_docstring,
            dry_run=args.dry_run,
        )
        stats.results.extend(results)
        for result in results:
            if result.is_error:
                stats.errors += 1
            elif result.comments_removed > 0 or result.docstrings_removed > 0:
                stats.changed_files += 1
                stats.comments_removed += result.comments_removed
                stats.docstrings_removed += result.docstrings_removed
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                _worker_process_file,
                (filepath, args.remove_module_docstring, args.dry_run),
            ): filepath
            for filepath in python_files
        }
        processed = 0
        for future in as_completed(futures):
            result = future.result()
            stats.results.append(result)
            if result.is_error:
                stats.errors += 1
            elif result.comments_removed > 0 or result.docstrings_removed > 0:
                stats.changed_files += 1
                stats.comments_removed += result.comments_removed
                stats.docstrings_removed += result.docstrings_removed
            processed += 1
            if processed % 10 == 0:
                print(f"  Processed: {processed}/{len(python_files)}", end="\r")
    if python_files:
        print(f"  Processed: {len(python_files)}/{len(python_files)}")
    base_dir = Path(args.path).resolve()
    print_results(stats, base_dir)
    print_summary(stats)
    return 0 if stats.errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
