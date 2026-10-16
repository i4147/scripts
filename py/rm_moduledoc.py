from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def clean_single_file(file_path: Path):
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
    except Exception as e:
        print(f"❌ Error reading {file_path.name}: {e}")
        return
    if not lines:
        return
    pattern = rf'^\s*"""\s*Module for\s+{re.escape(file_path.name)}\s*\.?\s*"""\s*$'
    modified = False
    scan_limit = min(5, len(lines))
    for i in range(scan_limit):
        if re.match(pattern, lines[i].strip()):
            lines.pop(i)
            modified = True
            break
    if modified:
        try:
            file_path.write_text("".join(lines), encoding="utf-8")
            print(f"✅ Cleaned docstring from line {i + 1} of: {file_path.name}")
        except Exception as e:
            print(f"❌ Error writing {file_path.name}: {e}")
    else:
        print(f"➖ No automated docstring in top 5 lines of: {file_path.name}")


def main():
    current_dir = Path(".")
    py_files = [f for f in current_dir.glob("*.py") if f.name != Path(__file__).name]
    if not py_files:
        print("No Python files found in the current directory.")
        return
    print(f"🚀 Scanning the top 5 lines of {len(py_files)} files in parallel...")
    with ThreadPoolExecutor() as executor:
        executor.map(clean_single_file, py_files)
    print("🎉 Fast cleanup complete!")


if __name__ == "__main__":
    raise SystemExit(main())
