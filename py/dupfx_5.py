import argparse
import concurrent.futures as cf
import os
from collections import defaultdict
from pathlib import Path

try:
    import xxhash
except ImportError:
    print("Error: 'xxhash' library not found. Please install it with 'pip install xxhash'.")
    exit(1)

SKIPPED_PATHS = []
EXCLUDED_DIRS = {".git", ".venv", "venv", "__pycache__"}


def hash_file(path_str: str, chunk_size: int = 65536):
    hasher = xxhash.xxh64()
    try:
        with open(path_str, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                hasher.update(chunk)
        return path_str, hasher.hexdigest()
    except (PermissionError, OSError):
        return path_str, None


def collect_all_files(directory: Path):
    files = []
    for root, dirs, fs in os.walk(directory, onerror=lambda e: None):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for f in fs:
            files.append(Path(root) / f)
    return files


def group_by_size(files):
    groups = defaultdict(list)
    for f in files:
        try:
            size = f.stat().st_size
            if size > 0:
                groups[size].append(f)
        except (PermissionError, OSError):
            SKIPPED_PATHS.append(str(f))
    return groups


def hash_groups_in_parallel(groups):
    candidates = []
    for _size, paths in groups.items():
        if len(paths) > 1:
            candidates.extend(paths)
    if not candidates:
        return {}
    hash_groups = defaultdict(list)

    with cf.ThreadPoolExecutor() as executor:
        futures = {executor.submit(hash_file, str(p)): p for p in candidates}
        for future in cf.as_completed(futures):
            path_str, h = future.result()
            if h is None:
                SKIPPED_PATHS.append(path_str)
                continue
            hash_groups[h].append(path_str)

    return {h: ps for h, ps in hash_groups.items() if len(ps) > 1}


def auto_delete_duplicates(dups: dict) -> None:
    print("\n🔥 AUTO-DELETE MODE: Removing duplicates...\n")
    deleted_count = 0
    for _h, files in dups.items():
        for f in files[1:]:
            try:
                os.remove(f)
                deleted_count += 1
            except Exception as e:
                print(f"⚠️ Could not delete {f}: {e}")
    print(f"\n✅ Deleted {deleted_count} duplicate files.")


def report_duplicates(dups: dict):
    dup_count = sum(len(files) - 1 for files in dups.values())
    dup_size = sum(Path(f).stat().st_size for files in dups.values() for f in files[1:])
    print(f"\n📊 Report:")
    print(f"   • Duplicate groups: {len(dups)}")
    print(f"   • Total redundant files: {dup_count}")
    print(f"   • Potential space savings: {dup_size / 1024 / 1024:.2f} MB")
    for h, files in dups.items():
        print(f"\nGroup {h}:")
        for f in files:
            print(f"  {f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ultra-Fast Duplicate Finder")
    parser.add_argument("-a", "--auto-delete", action="store_true", help="Automatically delete duplicates")
    args = parser.parse_args()
    target = Path.cwd()
    print(f"Scanning: {target}")
    all_files = collect_all_files(target)
    size_groups = group_by_size(all_files)
    duplicates = hash_groups_in_parallel(size_groups)
    if duplicates:
        report_duplicates(duplicates)
        if args.auto_delete:
            auto_delete_duplicates(duplicates)
    else:
        print("\n✅ No duplicates found.")
    if SKIPPED_PATHS:
        print(f"\n⚠️ Skipped {len(SKIPPED_PATHS)} files due to errors.")


if __name__ == "__main__":
    main()
