from __future__ import annotations

import re
import sys
from pathlib import Path

INFO_BLOCK_PATTERN = re.compile(
    r"^# Author\s*:\s*isaac\s*\n"
    r"# Email\s*:\s*mkalafsaz@gmail\.com\s*\n"
    r"# Time\s*:\s*.*?\n",
    re.MULTILINE,
)
PYTHON_SHEBANG_PATTERNS = [
    re.compile(r"^#!.*python", re.IGNORECASE),
    re.compile(r"^#!.*python3", re.IGNORECASE),
]


def is_python_file(file_path):
    if file_path.suffix == ".py":
        return True
    if not file_path.suffix:
        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                first_line = f.readline()
                for pattern in PYTHON_SHEBANG_PATTERNS:
                    if pattern.match(first_line):
                        return True
        except Exception:
            pass
    return False


def remove_info_block(file_path):
    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
        if "Author : isaac" not in content:
            return False
        new_content = INFO_BLOCK_PATTERN.sub("", content)
        if new_content != content:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            return True
        return False
    except Exception as e:
        print(f"Error processing {file_path}: {e}", file=sys.stderr)
        return False


def main():
    start_dir = Path(".")
    removed_count = 0
    files_checked = 0
    for file_path in start_dir.rglob("*"):
        if not file_path.is_file():
            continue
        name = file_path.name
        if name in [".DS_Store", ".gitignore", "README", "LICENSE", "Makefile"]:
            continue
        if not is_python_file(file_path):
            continue
        files_checked += 1
        if remove_info_block(file_path):
            print(f"✓ Removed info block from: {file_path}")
            removed_count += 1
    print("\nSummary:")
    print(f"  Python files checked: {files_checked}")
    print(f"  Info blocks removed: {removed_count}")


if __name__ == "__main__":
    raise SystemExit(main())
