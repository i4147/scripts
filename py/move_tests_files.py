from __future__ import annotations

import argparse
import json
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

TESTS_DIR = Path.home() / "tmp" / "tests"
MOVED_FILES_LOG = Path.home() / "tmp" / "moved_files.json"


def is_test_file(file_path: Path) -> bool:
    stem = file_path.stem
    return "_test" in stem or "test_" in stem


def get_relative_path(file_path: Path, base_dir: Path) -> Path:
    try:
        return file_path.relative_to(base_dir)
    except ValueError:
        return file_path


def move_file(source: Path, dest: Path) -> tuple[str, bool, str]:
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(dest))
        return str(source), True, f"Moved to {dest}"
    except Exception as e:
        return str(source), False, f"Error: {e!s}"


def find_test_files(base_dir: Path) -> list[Path]:
    test_files = []
    for py_file in base_dir.rglob("*.py"):
        if is_test_file(py_file):
            test_files.append(py_file)
    return test_files


def move_files_parallel(
    test_files: list[Path], base_dir: Path, max_workers: int = 4
) -> tuple[dict, list[tuple[str, str]]]:
    file_mapping = {}
    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for source_file in test_files:
            relative_path = get_relative_path(source_file, base_dir)
            dest_file = TESTS_DIR / relative_path
            future = executor.submit(move_file, source_file, dest_file)
            futures[future] = source_file, dest_file
        for future in as_completed(futures):
            source_file, dest_file = futures[future]
            _source_str, success, message = future.result()
            if success:
                file_mapping[str(source_file)] = str(dest_file)
                results.append((str(source_file), message))
                print(f"✓ {message}")
            else:
                results.append((str(source_file), message))
                print(f"✗ {message}")
    return file_mapping, results


def reverse_move(moved_files_log: Path) -> tuple[dict, list[tuple[str, str]]]:
    if not moved_files_log.exists():
        raise FileNotFoundError(f"Log file not found: {moved_files_log}")
    with open(moved_files_log) as f:
        file_mapping = json.load(f)
    results = []
    with ProcessPoolExecutor(max_workers=4) as executor:
        futures = {}
        for original_path, moved_path in file_mapping.items():
            moved_file = Path(moved_path)
            original_file = Path(original_path)
            if moved_file.exists():
                future = executor.submit(move_file, moved_file, original_file)
                futures[future] = moved_file, original_file
        for future in as_completed(futures):
            source_file, _dest_file = futures[future]
            _source_str, success, message = future.result()
            if success:
                results.append((str(source_file), message))
                print(f"✓ {message}")
            else:
                results.append((str(source_file), message))
                print(f"✗ {message}")
    return file_mapping, results


def save_log(file_mapping: dict, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w") as f:
        json.dump(file_mapping, f, indent=2)
    print(f"\n📋 Log saved to: {log_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Move Python test files to ~/tmp/tests with directory structure preservation."
    )
    parser.add_argument(
        "--reverse",
        action="store_true",
        help="Reverse the move operation (return files to original locations).",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path.cwd(),
        help="Base directory to search for test files (default: current directory).",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=MOVED_FILES_LOG,
        help=f"Path to log file (default: {MOVED_FILES_LOG}).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4).",
    )
    args = parser.parse_args()
    try:
        if args.reverse:
            print(f"🔄 Reversing move operation from log: {args.log}")
            file_mapping, results = reverse_move(args.log)
            print(f"\n✅ Reversed {len(results)} files")
            try:
                for parent in TESTS_DIR.rglob("*"):
                    if parent.is_dir() and not any(parent.iterdir()):
                        parent.rmdir()
            except OSError:
                pass
        else:
            print(f"🔍 Searching for test files in: {args.dir}")
            test_files = find_test_files(args.dir)
            if not test_files:
                print("❌ No test files found.")
                sys.exit(0)
            print(f"📦 Found {len(test_files)} test file(s)")
            print(f"📍 Destination: {TESTS_DIR}\n")
            file_mapping, results = move_files_parallel(test_files, args.dir, max_workers=args.workers)
            save_log(file_mapping, args.log)
            print(f"\n✅ Moved {len(file_mapping)} file(s)")
    except FileNotFoundError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
