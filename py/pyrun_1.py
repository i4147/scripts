#!/data/data/com.termux/files/usr/bin/python

from __future__ import annotations

import argparse
import multiprocessing
import runpy
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from loguru import logger

NUM_WORKERS: int = 8
DEFAULT_TIMEOUT: int = 10
MAX_ERROR_MSG_LEN: int = 200


def run_python_file(path: Path, timeout: int = DEFAULT_TIMEOUT) -> tuple[Path, bool, str | None, str | None]:
    try:
        result = runpy.run_path(
            str(path),
            run_name="__main__",
        )
        _ = result
        return (path, True, None, None)
    except SystemExit as e:
        code = e.code
        if code in (0, None):
            return (path, True, None, None)
        return (
            path,
            False,
            f"SystemExit (code: {code})",
            f"Process exited with code {code}",
        )
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e!s}"
        error_type = _classify_exception(e)
        return (path, False, error_type, error_msg)


def _classify_exception(exc: BaseException) -> str:
    name = type(exc).__name__
    known = {
        "ModuleNotFoundError",
        "SyntaxError",
        "ImportError",
        "AttributeError",
        "TypeError",
        "ValueError",
        "KeyboardInterrupt",
        "TimeoutError",
    }
    if name in known:
        return name
    if isinstance(exc, ModuleNotFoundError):
        return "ModuleNotFoundError"
    if isinstance(exc, SyntaxError):
        return "SyntaxError"
    if isinstance(exc, ImportError):
        return "ImportError"
    if isinstance(exc, TimeoutError):
        return "TimeoutError"
    if isinstance(exc, KeyboardInterrupt):
        return "KeyboardInterrupt"
    return f"RuntimeError ({name})"


def _run_with_timeout(path: Path, timeout: int) -> tuple[Path, bool, str | None, str | None]:
    try:
        proc = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(path.parent),
        )
    except subprocess.TimeoutExpired:
        return (
            path,
            False,
            "TimeoutError",
            f"Execution exceeded {timeout} seconds",
        )
    except subprocess.SubprocessError as e:
        return (path, False, "SubprocessError", str(e))
    except Exception as e:
        return (
            path,
            False,
            "UnexpectedError",
            f"{type(e).__name__}: {e!s}",
        )
    if proc.returncode == 0:
        return (path, True, None, None)
    stderr = (proc.stderr or "").lower()
    error_msg = (proc.stderr or proc.stdout or "").strip()
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
        error_type = f"RuntimeError (exit code: {proc.returncode})"
    return (path, False, error_type, error_msg)


def _worker_entry(path: Path, timeout: int) -> tuple[Path, bool, str | None, str | None]:
    return _run_with_timeout(path, timeout)


def find_python_files(root_dir: Path, recursive: bool = True) -> list[Path]:
    if recursive:
        return sorted(root_dir.rglob("*.py"))
    return sorted(root_dir.glob("*.py"))


def run_files_parallel(
    files: list[Path],
    timeout: int = DEFAULT_TIMEOUT,
    verbose: bool = False,
) -> dict[str, list[Any]]:
    results: dict[str, list[Any]] = {"success": [], "failed": []}
    if not files:
        return results
    pool = multiprocessing.Pool(processes=NUM_WORKERS)
    try:
        async_results = [pool.apply_async(_worker_entry, args=(path, timeout)) for path in files]
        pool.close()
        for path, async_result in zip(files, async_results, strict=True):
            try:
                result_path, success, error_type, error_msg = async_result.get()
                if success:
                    results["success"].append(result_path)
                    if verbose:
                        logger.success(f"{result_path}")
                else:
                    results["failed"].append((result_path, error_type, error_msg))
                    if verbose:
                        logger.error(f"{result_path}: {error_type}")
                        if error_msg:
                            logger.debug(f"   {error_msg}")
            except Exception as e:
                results["failed"].append((path, "FutureError", str(e)))
                if verbose:
                    logger.error(f"{path}: FutureError - {e}")
        pool.join()
    except KeyboardInterrupt:
        pool.terminate()
        pool.join()
        raise
    return results


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=("Recursively run Python files with timeout and parallel processing"))
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
        default=DEFAULT_TIMEOUT,
        help=f"Timeout in seconds per file (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print detailed output",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_false",
        dest="recursive",
        help="Don't scan subdirectories",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    root_dir = Path(args.directory).resolve()
    if not root_dir.exists():
        logger.error(f"Directory '{root_dir}' does not exist")
        return 1
    if not root_dir.is_dir():
        logger.error(f"'{root_dir}' is not a directory")
        return 1
    mode = "recursively" if args.recursive else "non-recursively"
    print(f"Scanning {mode} in: {root_dir}")
    files = find_python_files(root_dir, args.recursive)
    if not files:
        logger.warning("No Python files found.")
        return 0
    print(f"Found {len(files)} Python files")
    print(f"Using {NUM_WORKERS} workers with {args.timeout}s timeout per file")
    print("-" * 40)
    start_time = time.time()
    try:
        results = run_files_parallel(
            files=files,
            timeout=args.timeout,
            verbose=args.verbose,
        )
    except KeyboardInterrupt:
        logger.warning("Interrupted by user.")
        return 130
    elapsed_time = time.time() - start_time
    print("=" * 40)
    print("SUMMARY")
    print("-" * 40)
    print(f"Total files: {len(files)}")
    print(f"Successfully ran: {len(results['success'])}")
    print(f"Failed: {len(results['failed'])}")
    print(f"Time elapsed: {elapsed_time:.2f} seconds")
    failed = results["failed"]
    if failed:
        print("-" * 40)
        print("FAILED FILES:")
        print("-" * 40)
        for path, error_type, error_msg in failed:
            logger.error(f"{path}")
            logger.error(f"   Error: {error_type}")
            if error_msg:
                if len(error_msg) > MAX_ERROR_MSG_LEN:
                    error_msg = error_msg[:MAX_ERROR_MSG_LEN] + "..."
                logger.error(f"   Message: {error_msg}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
