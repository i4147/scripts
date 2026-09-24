import ast
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from dh import get_pyfiles


MAX_WORKERS: Final[int] = 4
PRESERVE_PATTERNS: Final[tuple[str, ...]] = (
    r"^#!",
    r"#\s*type:",
    r"#\s*fmt:",
    r"#\s*pragma:",
    r"#\s*noqa",
    r"#\s*pylint:",
    r"#\s*flake8:",
    r"#\s*mypy:",
)


@dataclass(slots=True)
class FileProcessingResult:
    file_path: Path
    was_modified: bool
    removed_count: int
    elapsed_ms: float
    syntax_valid: bool


class CommentRemover:
    __slots__ = ("preserve_regex",)

    def __init__(self) -> None:
        self.preserve_regex = re.compile("|".join(PRESERVE_PATTERNS))

    def remove_comments(self, content: str) -> tuple[str, int]:
        lines = content.splitlines(keepends=True)
        modified_lines: list[str] = []
        removed_count = 0
        in_string = False
        string_char: str | None = None
        for line in lines:
            new_line_chars: list[str] = []
            i = 0
            in_comment = False
            escape_next = False
            while i < len(line):
                char = line[i]

                if escape_next:
                    if not in_comment:
                        new_line_chars.append(char)
                    escape_next = False
                    i += 1
                    continue
                if char == "\\":
                    escape_next = True
                    if not in_comment:
                        new_line_chars.append(char)
                    i += 1
                    continue

                if not in_comment and char in ('"', "'"):
                    if not in_string:
                        in_string = True
                        string_char = char
                    elif string_char == char:
                        in_string = False
                        string_char = None
                    new_line_chars.append(char)
                    i += 1
                    continue

                if not in_string and char == "#" and not in_comment:
                    remaining_line = line[i:]
                    if self.preserve_regex.search(remaining_line):
                        new_line_chars.extend(line[i:])
                        break
                    else:
                        in_comment = True

                        while new_line_chars and new_line_chars[-1] in (" ", "\t"):
                            new_line_chars.pop()
                        i += 1
                        continue
                if not in_comment:
                    new_line_chars.append(char)
                i += 1

            result_line = "".join(new_line_chars)

            if line.endswith("\n") and not result_line.endswith("\n"):
                result_line += "\n"
            modified_lines.append(result_line)
            if in_comment:
                removed_count += 1
        return "".join(modified_lines), removed_count


def validate_python_syntax(content: str) -> tuple[bool, str]:
    try:
        ast.parse(content)
        return True, ""
    except SyntaxError as e:
        return False, f"Line {e.lineno}: {e.msg}"
    except Exception as e:
        return False, str(e)


def process_file(file_path: Path) -> FileProcessingResult:
    start_time = time.perf_counter()
    try:
        original_content = file_path.read_text(encoding="utf-8")
        remover = CommentRemover()
        modified_content, removed_count = remover.remove_comments(original_content)
        was_modified = False
        syntax_valid = True
        if modified_content != original_content and removed_count > 0:
            is_valid, error_msg = validate_python_syntax(modified_content)
            if is_valid:
                file_path.write_text(modified_content, encoding="utf-8")
                was_modified = True
            else:
                syntax_valid = False
                print(
                    f"  ⚠ Warning: {file_path} would have syntax error, skipping write: {error_msg}",
                    file=sys.stderr,
                )
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return FileProcessingResult(file_path, was_modified, removed_count, elapsed_ms, syntax_valid)
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        print(f"Error processing {file_path}: {e}", file=sys.stderr)
        return FileProcessingResult(file_path, False, 0, elapsed_ms, False)


def format_report(result: FileProcessingResult) -> str:
    if not result.syntax_valid:
        return f"{result.file_path} {result.elapsed_ms:.0f}ms (SKIPPED - syntax error)"
    if result.was_modified:
        count = result.removed_count
        plural = "s" if count != 1 else ""
        return f"{result.file_path} {result.elapsed_ms:.0f}ms ({count} comment{plural} removed)"
    return f"{result.file_path} {result.elapsed_ms:.0f}ms (no change)"


def main() -> None:
    cwd = Path.cwd()
    python_files = get_pyfiles(cwd)
    if not python_files:
        print("No Python files found.")
        return
    print(f"Found {len(python_files)} Python file(s) to process\n")
    total_start = time.perf_counter()
    results: list[FileProcessingResult] = []
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_file = {executor.submit(process_file, file_path): file_path for file_path in python_files}
        for future in as_completed(future_to_file):
            file_path = future_to_file[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                print(f"Error processing {file_path}: {e}", file=sys.stderr)
                results.append(FileProcessingResult(file_path, False, 0, 0, False))
    total_elapsed = (time.perf_counter() - total_start) * 1000
    total_modified = 0
    total_removed = 0
    total_skipped = 0
    for result in results:
        print(format_report(result))
        if result.was_modified:
            total_removed += result.removed_count
            total_modified += 1
        elif not result.syntax_valid and result.removed_count > 0:
            total_skipped += 1
    print(f"\nSummary: {total_modified} file(s) modified, {total_removed} comment(s) removed")
    if total_skipped > 0:
        print(f"  ⚠ {total_skipped} file(s) skipped due to syntax errors")
    print(f"Total time: {total_elapsed:.0f}ms")


if __name__ == "__main__":
    main()
