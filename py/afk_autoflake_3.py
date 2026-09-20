from __future__ import annotations

import argparse
import multiprocessing as mp
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
            return
        elif result.returncode == 1:
            if autofix:
                print(f"Successfully removed unused imports from `{path}`.")
            else:
                
                output = (result.stdout or "") + (result.stderr or "")
                for line in output.splitlines():
                    if line.strip():
                        print(f"{path}: {line}")
    except FileNotFoundError:
        print("Error: `autoflake` is not installed. Run `pip install autoflake`.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check or fix unused imports in Python file(s).")
    parser.add_argument(
        "file",
        nargs="?",
        help="Path to the Python file (if omitted, processes all .py files in current dir)",
    )
    parser.add_argument(
        "-a",
        "--autofix",
        action="store_true",
        help="Automatically remove unused imports",
    )
    args = parser.parse_args()

    if args.file:
        check_or_fix_imports(args.file, args.autofix)
    else:
        files = sorted(str(p) for p in Path.cwd().glob("*.py"))
        if files:
            with mp.Pool(processes=8) as pool:
                results = [pool.apply_async(check_or_fix_imports, (f, args.autofix)) for f in files]
                for r in results:
                    r.wait()
