from __future__ import annotations

import argparse
import ast
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional
from zipfile import ZIP_DEFLATED, ZipFile

from dh import DOC_TH1, DOC_TH2


class CodeCleaner:
    def __init__(
        self,
        remove_comments: bool = False,
        remove_docstrings: bool = False,
        validate: bool = True,
        workers: int = 4,
        verbose: bool = False,
        apply: bool = False,
    ):
        self.remove_comments = remove_comments
        self.remove_docstrings = remove_docstrings
        self.validate = validate
        self.workers = workers
        self.verbose = verbose
        self.apply = apply
        self.modified_files = []

    def _should_preserve_comment(self, comment_text: str) -> bool:
        stripped = comment_text.lstrip("#").strip()
        return stripped.startswith(("type:", "fmt:", "noqa", "pylint:", "mypy:", "pragma:"))

    def remove_comments_and_docstrings(self, source: str) -> tuple[str, int, int]:
        lines = source.split("\n")
        result_lines = []
        comments_removed = 0
        docstrings_removed = 0

        in_multiline = False
        multiline_delim = None
        module_docstring_seen = False
        skip_count = 0

        for line_idx, line in enumerate(lines):
            if line_idx == 0 and line.startswith("#!"):
                result_lines.append(line)
                module_docstring_seen = False
                continue

            for delim in (DOC_TH1, DOC_TH2):
                count = line.count(delim)
                if count % 2 == 1:
                    if not in_multiline:
                        in_multiline = True
                        multiline_delim = delim
                    elif multiline_delim == delim:
                        in_multiline = False

            if in_multiline:
                is_module_doc = not module_docstring_seen and line_idx < 20 and (DOC_TH1 in line or DOC_TH2 in line)

                if is_module_doc:
                    module_docstring_seen = True
                    result_lines.append(line)
                elif self.remove_docstrings:
                    docstrings_removed += 1
                else:
                    result_lines.append(line)
                continue

            cleaned_line = ""
            in_string = False
            string_char = None
            i = 0
            comment_start = -1

            while i < len(line):
                char = line[i]

                if char in ('"', "'") and (i == 0 or line[i - 1] != "\\"):
                    if not in_string:
                        in_string = True
                        string_char = char
                    elif char == string_char:
                        in_string = False

                if char == "#" and not in_string:
                    comment_start = i
                    break

                cleaned_line += char
                i += 1

            if comment_start != -1:
                comment_text = line[comment_start:]

                if self._should_preserve_comment(comment_text):
                    cleaned_line = line
                elif self.remove_comments:
                    cleaned_line = cleaned_line.rstrip()
                    comments_removed += 1
                else:
                    cleaned_line = line
            else:
                cleaned_line = line

            result_lines.append(cleaned_line)

        while result_lines and not result_lines[-1].strip():
            result_lines.pop()

        result = "\n".join(result_lines)
        if result and not result.endswith("\n"):
            result += "\n"

        return (result, comments_removed, docstrings_removed)

    def _validate_code(self, code: str) -> bool:
        try:
            ast.parse(code)
            return True
        except SyntaxError:
            return False

    def process_file(self, file_path: Path) -> Optional[dict]:
        try:
            source = file_path.read_text(encoding="utf-8")
            cleaned, comments_removed, docstrings_removed = self.remove_comments_and_docstrings(source)

            if cleaned == source:
                return None

            if self.validate and not self._validate_code(cleaned):
                print(
                    f"[VALIDATION ERROR] {file_path}: Cleaned code has syntax errors",
                    file=sys.stderr,
                )
                return None

            result = {
                "path": file_path,
                "comments_removed": comments_removed,
                "docstrings_removed": docstrings_removed,
                "modified": True,
            }

            if self.apply:
                file_path.write_text(cleaned, encoding="utf-8")
                if self.verbose:
                    print(f"[APPLIED] {file_path}")
            else:
                if self.verbose:
                    print(f"[DRY RUN] {file_path}")

            return result

        except Exception as e:
            print(f"[ERROR] {file_path}: {e}", file=sys.stderr)
            return None

    def process_wheel(self, wheel_path: Path) -> Optional[dict]:
        try:
            temp_dir = Path(wheel_path.stem)
            temp_dir.mkdir(exist_ok=True)

            with ZipFile(wheel_path, "r") as z:
                z.extractall(temp_dir)

            py_files = list(temp_dir.rglob("*.py"))
            if not py_files:
                return None

            total_comments = 0
            total_docstrings = 0
            files_modified = 0

            for py_file in py_files:
                result = self.process_file(py_file)
                if result:
                    total_comments += result["comments_removed"]
                    total_docstrings += result["docstrings_removed"]
                    files_modified += 1

            if files_modified == 0:
                import shutil

                shutil.rmtree(temp_dir)
                return None

            result = {
                "path": wheel_path,
                "files_modified": files_modified,
                "comments_removed": total_comments,
                "docstrings_removed": total_docstrings,
                "modified": True,
            }

            if self.apply:
                with ZipFile(wheel_path, "w", ZIP_DEFLATED) as z:
                    for file in temp_dir.rglob("*"):
                        if file.is_file():
                            arcname = file.relative_to(temp_dir)
                            z.write(file, arcname)
                if self.verbose:
                    print(f"[APPLIED] {wheel_path}")

            import shutil

            shutil.rmtree(temp_dir)

            return result

        except Exception as e:
            print(f"[ERROR] {wheel_path}: {e}", file=sys.stderr)
            return None

    def process_paths(self, paths: list[Path]) -> None:
        py_files = []
        whl_files = []

        for path in paths:
            if path.is_file():
                if path.suffix == ".py":
                    py_files.append(path)
                elif path.suffix == ".whl":
                    whl_files.append(path)
            elif path.is_dir():
                py_files.extend(path.rglob("*.py"))
                whl_files.extend(path.rglob("*.whl"))

        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            if py_files:
                py_results = list(executor.map(self.process_file, py_files))
                for result in py_results:
                    if result:
                        self.modified_files.append(result)

            if whl_files:
                whl_results = list(executor.map(self.process_wheel, whl_files))
                for result in whl_results:
                    if result:
                        self.modified_files.append(result)

        self._print_summary()

    def _print_summary(self) -> None:
        mode = "APPLIED" if self.apply else "DRY RUN"

        if not self.modified_files:
            print(f"No files would be modified ({mode}).")
            return

        print(f"{mode}: Would modify {len(self.modified_files)} file(s):\n")

        for result in self.modified_files:
            path = result["path"]
            print(f"  {path}")

            if "files_modified" in result:
                print(
                    f"    Files: {result['files_modified']}, "
                    f"Comments: {result['comments_removed']}, "
                    f"Docstrings: {result['docstrings_removed']}"
                )
            else:
                print(f"    Comments: {result['comments_removed']}, Docstrings: {result['docstrings_removed']}")

        if not self.apply:
            print("\nThis was a dry run. Use -a/--apply to modify files.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove comments and docstrings from Python code.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -c myfile.py              
  %(prog)s -c -a myfile.py           
  %(prog)s -d -a myfile.py           
  %(prog)s -c -d -a myfile.py        
  %(prog)s -c -w 8 /path/to/code     
  %(prog)s -c -a --no-validate file.py  
        """,
    )

    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Python files or directories to process",
    )
    parser.add_argument(
        "-c",
        "--comments",
        action="store_true",
        help="Remove comments",
    )
    parser.add_argument(
        "-d",
        "--docstrings",
        action="store_true",
        help="Remove docstrings (except module docstrings)",
    )
    parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="Apply changes (default is dry run)",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Disable AST validation",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=8,
        help="Number of parallel workers (default: 4)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    if not args.comments and not args.docstrings:
        print(
            "Error: At least one of -c/--comments or -d/--docstrings must be specified.",
            file=sys.stderr,
        )
        sys.exit(1)

    for path in args.paths:
        if not path.exists():
            print(f"Error: Path does not exist: {path}", file=sys.stderr)
            sys.exit(1)

    cleaner = CodeCleaner(
        remove_comments=args.comments,
        remove_docstrings=args.docstrings,
        validate=not args.no_validate,
        workers=args.workers,
        verbose=args.verbose,
        apply=args.apply,
    )

    cleaner.process_paths(args.paths)


if __name__ == "__main__":
    raise SystemExit(main())
