from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


def find_notebook_files(paths: list[Path]) -> set[Path]:
    notebook_files = set()
    for path in paths:
        if not path.exists():
            print(f"Warning: {path} does not exist, skipping.", file=sys.stderr)
            continue
        if path.is_file():
            if path.suffix == ".ipynb":
                notebook_files.add(path.resolve())
            else:
                print(f"Warning: {path} is not a .ipynb file, skipping.", file=sys.stderr)
        elif path.is_dir():
            for nb_file in path.rglob("*.ipynb"):
                if ".ipynb_checkpoints" not in str(nb_file):
                    notebook_files.add(nb_file.resolve())
    return notebook_files


def strip_notebook_output(notebook_path: Path) -> tuple:
    try:
        with open(notebook_path, "r", encoding="utf-8") as f:
            notebook = json.load(f)
        if "cells" not in notebook:
            return (notebook_path, False, "Not a valid notebook (no 'cells' key)")
        modified = False
        for cell in notebook["cells"]:
            if cell.get("cell_type") == "code":
                if cell.get("outputs"):
                    cell["outputs"] = []
                    modified = True
                if "execution_count" in cell and cell["execution_count"] is not None:
                    cell["execution_count"] = None
                    modified = True
        if "metadata" in notebook and "kernelspec" in notebook["metadata"]:
            pass
        if modified:
            with open(notebook_path, "w", encoding="utf-8") as f:
                json.dump(notebook, f, indent=1, ensure_ascii=False)
                f.write("\n")
            return (notebook_path, True, "Outputs stripped")
        else:
            return (notebook_path, True, "No outputs to strip")
    except json.JSONDecodeError as e:
        return (notebook_path, False, f"Invalid JSON: {e}")
    except Exception as e:
        return (notebook_path, False, f"Error: {e}")


def process_notebooks(paths: list[Path], max_workers: int | None = None):
    notebook_files = find_notebook_files(paths)
    if not notebook_files:
        print("No .ipynb files found to process.")
        return
    print(f"Found {len(notebook_files)} notebook(s) to process...")
    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_path = {executor.submit(strip_notebook_output, path): path for path in notebook_files}
        for future in as_completed(future_to_path):
            path, success, message = future.result()
            results.append((path, success, message))
            status = "✓" if success else "✗"
            relative_path = path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path
            print(f"{status} {relative_path}: {message}")
    successful = sum(1 for _, success, _ in results if success)
    failed = len(results) - successful
    if failed > 0:
        print(f"\nProcessed: {successful} succeeded, {failed} failed")
    else:
        print(f"\nSuccessfully processed {successful} notebook(s)")


def main():
    parser = argparse.ArgumentParser(
        description="Strip outputs from Jupyter notebook (.ipynb) files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s
  %(prog)s notebook.ipynb
  %(prog)s dir1/ dir2/
  %(prog)s *.ipynb
  %(prog)s -w 4 .
        """,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to process (default: current directory)",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=None,
        help="Number of worker processes (default: CPU count)",
    )
    args = parser.parse_args()
    paths = [Path(p) for p in args.paths]
    try:
        process_notebooks(paths, max_workers=args.workers)
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
