
import re
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Tuple
import sys


class CommentRemover:

    def __init__(self) -> None:
        
        self.preserve_patterns = [
            r"^#!",  
            r"^#\s*type:",  
            r"^#\s*fmt:",  
            r"^#\s*pragma:",  
            r"^#\s*noqa",  
            r"^#\s*pylint:",  
            r"^#\s*flake8:",  
            r"^#\s*mypy:",  
        ]

        
        self.preserve_regex = re.compile("|".join(self.preserve_patterns), re.MULTILINE)

        
        self.comment_pattern = re.compile(r'(?<=^|[^\\"\'#])(#.*?$)', re.MULTILINE)

    def remove_comments(self, content: str) -> Tuple[str, int]:
        lines = content.splitlines(keepends=True)
        modified_lines = []
        removed_count = 0
        in_string = False
        string_char = None
        escape_next = False

        for line in lines:
            
            stripped_line = line.lstrip()
            if self.preserve_regex.match(stripped_line):
                modified_lines.append(line)
                continue

            
            new_line = []
            i = 0
            line_has_comment = False
            comment_start = -1

            while i < len(line):
                char = line[i]

                
                if escape_next:
                    new_line.append(char)
                    escape_next = False
                    i += 1
                    continue

                if char == "\\":
                    escape_next = True
                    new_line.append(char)
                    i += 1
                    continue

                
                if char in ('"', "'") and not escape_next:
                    if not in_string:
                        in_string = True
                        string_char = char
                        new_line.append(char)
                    elif string_char == char:
                        in_string = False
                        string_char = None
                        new_line.append(char)
                    else:
                        new_line.append(char)
                    i += 1
                    continue

                
                if char == "#" and not in_string:
                    line_has_comment = True
                    comment_start = i
                    break
                else:
                    new_line.append(char)

                i += 1

            if line_has_comment:
                
                comment_part = line[comment_start:]
                comment_stripped = comment_part.lstrip("#").lstrip()

                
                is_preserved = False
                for pattern in self.preserve_patterns:
                    if re.match(pattern, comment_part):
                        is_preserved = True
                        break

                if is_preserved:
                    
                    new_line.append(comment_part)
                else:
                    
                    removed_count += 1
                    
                    while new_line and new_line[-1] in (" ", "\t"):
                        new_line.pop()
                    
                    if comment_start > 0 and line[comment_start - 1] in (" ", "\t"):
                        pass  

                
                
                if line.endswith("\n"):
                    if not (new_line and new_line[-1] == "\n"):
                        new_line.append("\n")

                modified_lines.append("".join(new_line))
            else:
                modified_lines.append(line)

        return "".join(modified_lines), removed_count


def process_file(file_path: Path) -> Tuple[Path, bool, int, float]:
    start_time = time.perf_counter()

    try:
        
        original_content = file_path.read_text(encoding="utf-8")

        
        remover = CommentRemover()
        modified_content, removed_count = remover.remove_comments(original_content)

        
        if modified_content != original_content and removed_count > 0:
            file_path.write_text(modified_content, encoding="utf-8")
            was_modified = True
        else:
            was_modified = False

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return file_path, was_modified, removed_count, elapsed_ms

    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        print(f"Error processing {file_path}: {e}", file=sys.stderr)
        return file_path, False, 0, elapsed_ms


def find_python_files(directory: Path) -> list:
    return list(directory.rglob("*.py"))


def format_report(file_path: Path, was_modified: bool, count: int, elapsed_ms: float) -> str:
    if was_modified:
        status = f"{count} comment{'s' if count != 1 else ''} removed"
        return f"{file_path} {elapsed_ms:.0f}ms ({status})"
    else:
        return f"{file_path} {elapsed_ms:.0f}ms (no change)"


def main() -> None:
    current_dir = Path.cwd()

    print(f"Removing comments from Python files in: {current_dir}")
    print("Preserving: shebang (#!), type comments (# type:), fmt comments (# fmt:)")
    print("-" * 70)

    
    python_files = find_python_files(current_dir)

    if not python_files:
        print("No Python files found.")
        return

    print(f"Found {len(python_files)} Python file(s) to process\n")

    
    results = []
    total_start = time.perf_counter()

    with ProcessPoolExecutor() as executor:
        
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

    for file_path, was_modified, count, elapsed_ms in results:
        print(format_report(file_path, was_modified, count, elapsed_ms))
        if was_modified:
            total_removed += count
            total_modified += 1

    
    print("-" * 70)
    print(f"Summary: {total_modified} file(s) modified, {total_removed} comment(s) removed")
    print(f"Total time: {total_elapsed:.0f}ms")

    
    if len(results) < len(python_files):
        skipped = len(python_files) - len(results)
        print(f"Warning: {skipped} file(s) could not be processed")


if __name__ == "__main__":
    main()
