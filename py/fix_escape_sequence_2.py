from __future__ import annotations
import difflib
import re
from pathlib import Path


def show_diff(text1: str, text2: str) -> None:
    diff = difflib.unified_diff(text1.splitlines(keepends=True), text2.splitlines(keepends=True), lineterm="")
    changed_lines = [line for line in diff if line.startswith(("+", "-"))]
    if changed_lines:
        print("--- Differences ---")
        for line in changed_lines:
            print(line, end="")
        print("-----------------")


def fix_escape_sequences(directory: Path) -> None:
    for path in directory.rglob("*.py"):
        if not path.is_symlink():
            try:
                content = path.read_text(encoding="utf-8")
                pattern = re.compile(r"^(\s*\w+\s*=\s*)([\"\'])(?![rR])(.*?)\2", re.MULTILINE)

                def replacer(match):
                    var_name_part = match.group(1)
                    quote_char = match.group(2)
                    string_content = match.group(3)
                    needs_raw_conversion = False
                    if re.search(r"\\(?![\"\\ntrvaf0x\'])", string_content) or "\\\\" in string_content:
                        needs_raw_conversion = True
                    if re.search(r"\\(?![\\\'\"ntr\x00-\x1f_])", string_content):
                        needs_raw_conversion = True
                    if "\\\\" in string_content:
                        needs_raw_conversion = True
                    if needs_raw_conversion:
                        return f"{var_name_part}r{quote_char}{string_content}{quote_char}"
                    return match.group(0)

                new_content = pattern.sub(replacer, content)
                if new_content != content:
                    show_diff(content, new_content)
                    backup_path = path.with_name(path.name + ".bak")
                    backup_path.write_text(content, encoding="utf-8")
                    path.write_text(new_content, encoding="utf-8")
                    print(f"Fixed {path.relative_to(directory)}")
            except Exception as e:
                print(f"Error processing {path}: {e}")


if __name__ == "__main__":
    cwd = Path.cwd()
    fix_escape_sequences(cwd)
