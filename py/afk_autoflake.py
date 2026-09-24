from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def check_or_fix_imports(path, autofix=False):
    if not Path(path).exists():
        print(f"Error: The file `{path}` does not exist.")
        return
    command = [
        "autoflake",
        "--remove-all-unused-imports",
        "--ignore-init-module-imports",
        path,
    ]
    if autofix:
        command.append("--in-place")
    else:
        command.append("--check")
    try:
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            print("No unused imports found.")
        elif result.returncode == 1:
            if autofix:
                print(f"Successfully removed unused imports from `{path}`.")
            else:
                print(f"Unused imports found in `{path}`. Run with -a to fix.")
        else:
            print(f"An error occurred: {result.stderr}")
    except FileNotFoundError:
        print("Error: `autoflake` is not installed. Run `pip install autoflake`.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check or fix unused imports in a Python file.")
    parser.add_argument("file", help="Path to the Python file")
    parser.add_argument(
        "-a",
        "--autofix",
        action="store_true",
        help="Automatically remove unused imports",
    )
    args = parser.parse_args()
    check_or_fix_imports(args.file, args.autofix)
