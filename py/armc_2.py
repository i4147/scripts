
import ast
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Tuple

from dh import get_pyfiles


class CommentRemover:

    def __init__(self) -> None:
        
        self.preserve_patterns = [
            r"^#!",  
            r"#\s*type:",  
            r"#\s*fmt:",  
            r"#\s*pragma:",  
            r"#\s*noqa",  
            r"#\s*pylint:",  
            r"#\s*flake8:",  
            r"#\s*mypy:",  
        ]

        
        self.preserve_regex = re.compile("|".join(self.preserve_patterns))

    def remove_comments(self, content: str) -> Tuple[str, int]:
        lines = content.splitlines(keepends=True)
        modified_lines = []
        removed_count = 0
        in_string = False
        string_char = None
        escape_next = False

        for line in lines:
            
            new_line_chars = []
            i = 0
            comment_start = -1
            in_comment = False

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
                        new_line_chars.append(char)
                    elif string_char == char:
                        in_string = False
                        string_char = None
                        new_line_chars.append(char)
                    else:
                        new_line_chars.append(char)
                    i += 1
                    continue

                
                if not in_string and char == "#" and not in_comment:
                    
                    remaining_line = line[i:]
                    is_preserved = False

                    for pattern in self.preserve_patterns:
                        if re.search(pattern, remaining_line):
                            is_preserved = True
                            break

                    if is_preserved:
                        
                        new_line_chars.extend(line[i:])
                        break
                    else:
                        
                        in_comment = True
                        comment_start = i
                        
                        while new_line_chars and new_line_chars[-1] in (" ", "\t"):
                            new_line_chars.pop()
                        i += 1
                        continue

                
                if not in_comment:
                    new_line_chars.append(char)

                i += 1

            
            if not in_comment and comment_start == -1:
                
                modified_lines.append("".join(new_line_chars))
            else:
                
                if new_line_chars and new_line_chars[-1] == "\n":
                    modified_lines.append("".join(new_line_chars))
                else:
                    
                    result_line = "".join(new_line_chars)
                    if line.endswith("\n") and not result_line.endswith("\n"):
                        result_line += "\n"
                    modified_lines.append(result_line)
                if in_comment:
                    removed_count += 1

            
            
            if in_string and string_char:
                
                
                pass

        return "".join(modified_lines), removed_count


def validate_python_syntax(content: str) -> Tuple[bool, str]:
    try:
        ast.parse(content)
        return True, ""
    except SyntaxError as e:
        return False, f"Line {e.lineno}: {e.msg}"
    except Exception as e:
        return False, str(e)


def process_file(file_path: Path) -> Tuple[Path, bool, int, float, bool]:
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
                syntax_valid = True
            else:
                
                syntax_valid = False
                was_modified = False
                print(f"  ⚠ Warning: {file_path} would have syntax error, skipping write: {error_msg}", file=sys.stderr)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return file_path, was_modified, removed_count, elapsed_ms, syntax_valid

    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        print(f"Error processing {file_path}: {e}", file=sys.stderr)
        return file_path, False, 0, elapsed_ms, False


def find_python_files(directory: Path) -> list:
    return list(directory.rglob("*.py"))


def format_report(file_path: Path, was_modified: bool, count: int, elapsed_ms: float, syntax_valid: bool) -> str:
    if not syntax_valid:
        return f"{file_path} {elapsed_ms:.0f}ms (SKIPPED - syntax error)"
    elif was_modified:
        status = f"{count} comment{'s' if count != 1 else ''} removed"
        return f"{file_path} {elapsed_ms:.0f}ms ({status})"
    else:
        return f"{file_path} {elapsed_ms:.0f}ms (no change)"


def main() -> None:
    cwd = Path.cwd()

    
    python_files = get_pyfiles(cwd)

    if not python_files:
        print("No Python files found.")
        return

    print(f"Found {len(python_files)} Python file(s) to process\n")

    
    results = []
    total_start = time.perf_counter()

    with ProcessPoolExecutor(max_workers=4) as executor:
        
        future_to_file = {executor.submit(process_file, file_path): file_path for file_path in python_files}

        
        for future in as_completed(future_to_file):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                file_path = future_to_file[future]
                print(f"Error processing {file_path}: {e}", file=sys.stderr)

    total_elapsed = (time.perf_counter() - total_start) * 1000

    
    results.sort(key=lambda x: str(x[0]))

    
    total_removed = 0
    total_modified = 0
    total_skipped = 0

    for file_path, was_modified, count, elapsed_ms, syntax_valid in results:
        print(format_report(file_path, was_modified, count, elapsed_ms, syntax_valid))
        if was_modified:
            total_removed += count
            total_modified += 1
        elif not syntax_valid and count > 0:
            total_skipped += 1

    
    print("-" * 80)
    print(f"Summary: {total_modified} file(s) modified, {total_removed} comment(s) removed")
    if total_skipped > 0:
        print(f"  ⚠ {total_skipped} file(s) skipped due to syntax errors")
    print(f"Total time: {total_elapsed:.0f}ms")


if __name__ == "__main__":
    main()
