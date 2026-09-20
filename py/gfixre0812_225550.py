from __future__ import annotations

import ast
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def process_string_match(match: re.Match) -> str:
    raw_str = match.group(0)
    if "\\\\" in raw_str:
        if raw_str.startswith('"') and raw_str.endswith('"'):
            body = raw_str[1:-1]
            return 'r"' + body.replace("\\\\", "\\") + '"'
        elif raw_str.startswith("'") and raw_str.endswith("'"):
            body = raw_str[1:-1]
            return "r'" + body.replace("\\\\", "\\") + "'"
    return raw_str


def fix_file_regex_styles(file_path: Path):
    try:
        original_content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"❌ Error reading {file_path.name}: {e}")
        return
    string_pattern = "(?<![rRfFbB])(?:\"[^\"\\\\]*(?:\\\\.[^\"\\\\]*)*\"|\\'[^\\'\\\\]*(?:\\\\.[^\\'\\\\]*)*\\')"
    modified_content = re.sub(string_pattern, process_string_match, original_content)
    if original_content == modified_content:
        return
    try:
        ast.parse(modified_content)
    except SyntaxError as e:
        print(f"⚠️ AST Validation Failed for {file_path.name}! Preventing save. Error: {e}")
        return
    try:
        file_path.write_text(modified_content, encoding="utf-8")
        print(f"✅ Successfully restored raw regex format in: {file_path.name}")
    except Exception as e:
        print(f"❌ Error writing update to {file_path.name}: {e}")


def main():
    current_dir = Path(".")
    py_files = [f for f in current_dir.rglob("*.py") if f.is_file() and f.name != Path(__file__).name]
    if not py_files:
        print("No Python files found in the current directory.")
        return
    print(f"🚀 Found {len(py_files)} files. Restoring raw strings in parallel...")
    with ThreadPoolExecutor() as executor:
        executor.map(fix_file_regex_styles, py_files)
    print("🎉 Regex raw style transformation complete!")


if __name__ == "__main__":
    main()
