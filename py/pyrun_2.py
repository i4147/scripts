from __future__ import annotations

import argparse
import multiprocessing
import runpy
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


def run_python_file(file_path: Path, timeout: int = 10) -> tuple[Path, bool, str | None, str | None]:
    try:
        result = runpy(
            [sys.executable, str(file_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=file_path.parent,
        )
        if result.returncode == 0:
            return (file_path, True, None, None)
        else:
            stderr = result.stderr.lower()
            error_type = "Unknown Error"
            error_msg = result.stderr or result.stdout
            if "modulenotfounderror" in stderr or "no module named" in stderr:
                error_type = "ModuleNotFoundError"
            elif "syntaxerror" in stderr:
                error_type = "SyntaxError"
            elif "importerror" in stderr:
                error_type = "ImportError"
            elif "attributeerror" in stderr:
                error_type = "AttributeError"
            elif "typeerror" in stderr:
                error_type = "TypeError"
            elif "valueerror" in stderr:
                error_type = "ValueError"
            elif "keyboardinterrupt" in stderr:
                error_type = "KeyboardInterrupt"
            else:
                error_type = f"RuntimeError (exit code: {result.returncode})"
            return (file_path, False, error_type, error_msg.strip())
    except subprocess.TimeoutExpired:
        return (
            file_path,
            False,
            "TimeoutError",
            f"Execution exceeded {timeout} seconds",
        )
    except subprocess.SubprocessError as e:
        return (file_path, False, "SubprocessError", str(e))
    except Exception as e:
        return (file_path, False, "UnexpectedError", f"{type(e).__name__}: {e!s}")


def find_python_files(root_dir: Path, recursive: bool = True) -> list[Path]:
    if recursive:
        return sorted(root_dir.rglob("*.py"))
    else:
        return sorted(root_dir.glob("*.py"))


def run_files_parallel(
    files: list[Path],
    max_workers: int | None = None,
    timeout: int = 10,
    verbose: bool = False,
) -> dict[str, list[tuple[Path, str]]]:
    if max_workers is None:
        max_workers = min(multiprocessing.cpu_count(), len(files))
    results = {"success": [], "failed": []}
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {executor.submit(run_python_file, file_path, timeout): file_path for file_path in files}
        for future in as_completed(future_to_file):
            file_path = future_to_file[future]
            try:
                file_path, success, error_type, error_msg = future.result()
                if success:
                    results["success"].append(file_path)
                    if verbose:
                        print(f"✅ {file_path}")
                else:
                    results["failed"].append((file_path, error_type, error_msg))
                    if verbose:
                        print(f"❌ {file_path}: {error_type}")
                        if error_msg:
                            print(f"   {error_msg}")
            except Exception as e:
                results["failed"].append((file_path, "FutureError", str(e)))
                if verbose:
                    print(f"❌ {file_path}: FutureError - {e}")
    return results


def main():
    parser = argparse.ArgumentParser(description="Recursively run Python files with timeout and parallel processing")
    parser.add_argument(
        "directory",
        type=str,
        nargs="?",
        default=".",
        help="Directory to scan for Python files (default: current directory)",
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        default=True,
        help="Recursively search subdirectories (default: True)",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=int,
        default=10,
        help="Timeout in seconds per file (default: 10)",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers (default: CPU count)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Print detailed output")
    parser.add_argument(
        "--no-recursive",
        action="store_false",
        dest="recursive",
        help="Don't scan subdirectories",
    )
    args = parser.parse_args()
    root_dir = Path(args.directory).resolve()
    if not root_dir.exists():
        print(f"Error: Directory '{root_dir}' does not exist")
        sys.exit(1)
    if not root_dir.is_dir():
        print(f"Error: '{root_dir}' is not a directory")
        sys.exit(1)
    print(f"Scanning {('recursively' if args.recursive else 'non-recursively')} in: {root_dir}")
    files = find_python_files(root_dir, args.recursive)
    if not files:
        print("No Python files found.")
        return
    print(f"Found {len(files)} Python files")
    print(f"Using {args.workers or 'auto'} workers with {args.timeout}s timeout per file")
    print("-" * 40)
    start_time = time.time()
    results = run_files_parallel(
        files=files,
        max_workers=args.workers,
        timeout=args.timeout,
        verbose=args.verbose,
    )
    elapsed_time = time.time() - start_time
    print("\n" + "=" * 40)
    print("SUMMARY")
    print("-" * 40)
    print(f"Total files: {len(files)}")
    print(f"✅ Successfully ran: {len(results['success'])}")
    print(f"❌ Failed: {len(results['failed'])}")
    print(f"Time elapsed: {elapsed_time:.2f} seconds")
    if results["failed"]:
        print("\n" + "-" * 40)
        print("FAILED FILES:")
        print("-" * 40)
        for file_path, error_type, error_msg in results["failed"]:
            print(f"\n📁 {file_path}")
            print(f"   Error: {error_type}")
            if error_msg:
                if len(error_msg) > 200:
                    error_msg = error_msg[:200] + "..."
                print(f"   Message: {error_msg}")
    if results["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
