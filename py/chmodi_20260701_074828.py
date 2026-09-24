import stat
import sys
import time
from multiprocessing import Pool, cpu_count, Lock
from pathlib import Path


DIR_PERM = 0o755
FILE_PERM = 0o664
EXEC_PERM = 0o755


SKIP_NAMES = {".git", "__pycache__"}


EXECUTABLE_DIRS = {"bin", "sbin", ".bin", "libexec"}


stats = {
    "dirs_changed": 0,
    "files_changed": 0,
    "files_made_exec": 0,
    "skipped": 0,
    "errors": 0,
}


def is_executable(mode: int) -> bool:
    return bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))


def is_binary(file_path: Path) -> bool:
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(512)
        return b"\x00" in chunk
    except (OSError, IOError):
        return False


def has_shebang(file_path: Path) -> bool:
    try:
        with open(file_path, "rb") as f:
            first_line = f.readline()
        return first_line.startswith(b"#!")
    except (OSError, IOError):
        return False


def should_skip_path(path: Path) -> bool:
    for part in path.parts:
        if part in SKIP_NAMES:
            return True
    return False


def is_in_executable_dir(path: Path) -> bool:
    return any(part in EXECUTABLE_DIRS for part in path.parts)


def get_target_permission(path: Path, current_mode: int) -> tuple[int, str]:

    if path.is_dir():
        return DIR_PERM, "directory"

    if is_executable(current_mode):
        if is_binary(path) or has_shebang(path):
            return None, "executable binary/script"

        return FILE_PERM, "executable (normalize)"

    if is_in_executable_dir(path):
        return EXEC_PERM, "file in bin/sbin/.bin/libexec"

    return FILE_PERM, "regular file"


def process_path(path: Path) -> dict:
    result = {
        "dirs_changed": 0,
        "files_changed": 0,
        "files_made_exec": 0,
        "skipped": 0,
        "errors": 0,
        "messages": [],
    }

    try:
        if should_skip_path(path):
            result["skipped"] += 1
            return result

        try:
            current_mode = stat.S_IMODE(path.stat().st_mode)
        except FileNotFoundError:
            return result

        target_perm, reason = get_target_permission(path, current_mode)

        if target_perm is None:
            return result

        if current_mode == target_perm:
            return result

        path.chmod(target_perm)

        if path.is_dir():
            result["dirs_changed"] += 1
            result["messages"].append(f"[DIR]  {path:<60} {oct(current_mode)} -> {oct(target_perm)}")
        elif is_in_executable_dir(path) and not is_executable(current_mode):
            result["files_made_exec"] += 1
            result["messages"].append(f"[EXEC] {path:<60} {oct(current_mode)} -> {oct(target_perm)} ({reason})")
        else:
            result["files_changed"] += 1
            result["messages"].append(f"[FILE] {path:<60} {oct(current_mode)} -> {oct(target_perm)}")

    except PermissionError:
        result["errors"] += 1
        result["messages"].append(f"[PERM] Permission denied: {path}")
    except OSError as e:
        result["errors"] += 1
        result["messages"].append(f"[ERR]  {path}: {e}")
    except Exception as e:
        result["errors"] += 1
        result["messages"].append(f"[BUG]  {path}: Unexpected error: {e}")

    return result


def collect_paths(cwd: str) -> list[Path]:
    root = Path(cwd).resolve()

    if not root.exists():
        print(f"❌ Error: Path does not exist: {cwd}", file=sys.stderr)
        sys.exit(1)

    paths = []
    try:
        for p in root.rglob("*"):
            paths.append(p)
    except PermissionError as e:
        print(f"⚠️  Warning: Permission denied during traversal: {e}", file=sys.stderr)

    return paths


def merge_results(all_results: list[dict]) -> dict:
    merged = {
        "dirs_changed": 0,
        "files_changed": 0,
        "files_made_exec": 0,
        "skipped": 0,
        "errors": 0,
        "messages": [],
    }

    for result in all_results:
        merged["dirs_changed"] += result["dirs_changed"]
        merged["files_changed"] += result["files_changed"]
        merged["files_made_exec"] += result["files_made_exec"]
        merged["skipped"] += result["skipped"]
        merged["errors"] += result["errors"]
        merged["messages"].extend(result["messages"])

    return merged


def print_summary(results: dict, total_items: int, elapsed_time: float) -> None:
    print("\n" + "=" * 80)
    print("📊 PERMISSION NORMALIZATION SUMMARY")
    print("=" * 80)
    print(f"⏱️  Time elapsed:          {elapsed_time:.2f} seconds")
    print(f"📁 Total items processed: {total_items}")
    print(f"⏭️  Skipped:              {results['skipped']}")
    print("-" * 80)
    print(f"✓  Directories changed:   {results['dirs_changed']}")
    print(f"✓  Files normalized:      {results['files_changed']}")
    print(f"✓  Files made executable: {results['files_made_exec']}")
    print(f"❌ Errors encountered:    {results['errors']}")
    print("=" * 80)


def print_details(results: dict, verbose: bool = False) -> None:
    if not verbose or not results["messages"]:
        return

    print("\n📝 DETAILED CHANGES:")
    print("-" * 80)
    for msg in results["messages"][:100]:
        print(msg)

    if len(results["messages"]) > 100:
        print(f"\n... and {len(results['messages']) - 100} more changes")


def normalize_permissions(cwd: str = ".", verbose: bool = False) -> None:
    start_time = time.time()

    print(f"🔍 Scanning: {Path(cwd).resolve()}")
    all_paths = collect_paths(cwd)
    total = len(all_paths)

    if total == 0:
        print("⚠️  No files found to process.")
        return

    workers = cpu_count()
    print(f"📦 Found {total} items to process")
    print(f"⚙️  Using {workers} worker processes")
    print(f"🚀 Processing...\n")

    try:
        with Pool(processes=workers) as pool:
            results_list = pool.imap_unordered(process_path, all_paths, chunksize=max(100, total // (workers * 4)))

            all_results = []
            for i, result in enumerate(results_list, 1):
                all_results.append(result)

                if i % 1000 == 0:
                    print(f"  Progress: {i:,}/{total:,} ({100 * i / total:.1f}%)")

    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user!")
        sys.exit(1)

    final_results = merge_results(all_results)
    elapsed = time.time() - start_time

    print_summary(final_results, total, elapsed)
    print_details(final_results, verbose=verbose)

    print("\n✅ Done!")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Normalize file and directory permissions.",
        epilog="Example: python3 normalize_perms.py . -v",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to start normalization (default: current directory)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print detailed changes",
    )

    args = parser.parse_args()

    try:
        normalize_permissions(args.path, verbose=args.verbose)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted!")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
