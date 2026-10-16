import argparse
import json
import os
import pathlib
from collections import defaultdict
from datetime import datetime

import xxhash

BACKUP_FILE = ".symlink_backup.json"


def calculate_file_hash(filepath, chunk_size=8192) -> str | None:
    hasher = xxhash.xxh64()
    try:
        with pathlib.Path(filepath).open("rb") as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError as e:
        print(f"Error reading {filepath}: {e}")
        return None


def find_duplicates(directory: str = "."):
    print(f"Scanning directory: {pathlib.Path(directory).resolve()}")
    size_map = defaultdict(list)
    file_count = 0
    for root, dirs, files in os.walk(directory):
        if ".git" in dirs:
            dirs.remove(".git")
        for filename in files:
            if filename.startswith("."):
                continue
            filepath = os.path.join(root, filename)
            if pathlib.Path(filepath).is_symlink():
                continue
            try:
                size = pathlib.Path(filepath).stat().st_size
                size_map[size].append(filepath)
                file_count += 1
            except OSError as e:
                print(f"Error accessing {filepath}: {e}")
    print(f"Found {file_count} files")
    hash_map = defaultdict(list)
    potential_duplicates = [files for files in size_map.values() if len(files) > 1]
    print(f"Checking {sum(len(files) for files in potential_duplicates)} potential duplicates...")
    for files in potential_duplicates:
        for filepath in files:
            file_hash = calculate_file_hash(filepath)
            if file_hash:
                hash_map[file_hash].append(filepath)
    return {h: files for h, files in hash_map.items() if len(files) > 1}


def choose_keeper(files):
    return min(files, key=lambda f: (len(f), f))


def create_symlinks(duplicates, dry_run=False) -> int:
    backup_data = {
        "timestamp": datetime.now().isoformat(),
        "operations": [],
    }
    total_saved = 0
    symlink_count = 0
    for file_hash, files in duplicates.items():
        keeper = choose_keeper(files)
        keeper_abs = pathlib.Path(keeper).resolve()
        print(f"\nDuplicate group (hash: {file_hash[:16]}...):")
        print(f"  Keeping: {keeper}")
        for duplicate in files:
            if duplicate == keeper:
                continue
            duplicate_abs = pathlib.Path(duplicate).resolve()
            file_size = pathlib.Path(duplicate).stat().st_size
            print(f"  Symlinking: {duplicate} -> {keeper_abs}")
            if not dry_run:
                backup_data["operations"].append({
                    "symlink": duplicate_abs,
                    "target": keeper_abs,
                    "original_existed": True,
                    "size": file_size,
                })
                try:
                    pathlib.Path(duplicate).unlink()
                    pathlib.Path(duplicate_abs).symlink_to(keeper_abs)
                    symlink_count += 1
                    total_saved += file_size
                except OSError as e:
                    print(f"  Error: {e}")
            else:
                symlink_count += 1
                total_saved += file_size
    if not dry_run and symlink_count > 0:
        with pathlib.Path(BACKUP_FILE).open("w", encoding="utf-8") as f:
            json.dump(backup_data, f, indent=2)
        print(f"\nBackup data saved to {BACKUP_FILE}")
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Summary:")
    print(f"  Symlinks created: {symlink_count}")
    print(f"  Space saved: {total_saved / (1024 * 1024):.2f} MB")
    return symlink_count


def reverse_symlinks(
    backup_file: str = BACKUP_FILE,
) -> bool:
    if not pathlib.Path(backup_file).exists():
        print(f"Error: Backup file {backup_file} not found!")
        return False
    with pathlib.Path(backup_file).open("r", encoding="utf-8") as f:
        backup_data = json.load(f)
    print(f"Restoring from backup created at: {backup_data['timestamp']}")
    print(f"Operations to reverse: {len(backup_data['operations'])}")
    restored_count = 0
    for op in backup_data["operations"]:
        symlink_path = op["symlink"]
        target_path = op["target"]
        if not pathlib.Path(symlink_path).is_symlink():
            print(f"Warning: {symlink_path} is not a symlink, skipping")
            continue
        if not pathlib.Path(target_path).exists():
            print(f"Error: Target file {target_path} no longer exists!")
            continue
        try:
            pathlib.Path(symlink_path).unlink()
            import shutil

            shutil.copy2(target_path, symlink_path)
            restored_count += 1
            print(f"Restored: {symlink_path}")
        except OSError as e:
            print(f"Error restoring {symlink_path}: {e}")
    print(f"\nRestored {restored_count} files")
    backup_renamed = f"{backup_file}.restored.{datetime.now().strftime('%Y%m%d_%H%M%S')} "
    pathlib.Path(backup_file).rename(backup_renamed)
    print(f"Backup file renamed to: {backup_renamed}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Find duplicate files and replace with symlinks (reversible)")
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--reverse",
        action="store_true",
        help="Reverse previous symlinking operation",
    )
    parser.add_argument(
        "--backup-file",
        default=BACKUP_FILE,
        help=f"Backup file path (default: {BACKUP_FILE})",
    )
    args = parser.parse_args()
    if args.reverse:
        reverse_symlinks(args.backup_file)
    else:
        duplicates = find_duplicates(args.directory)
        if not duplicates:
            print("\nNo duplicates found!")
            return
        print(f"\nFound {len(duplicates)} groups of duplicates")
        print(f"Total duplicate files: {sum(len(files) - 1 for files in duplicates.values())}")
        if args.dry_run:
            print("\n[DRY RUN MODE - No changes will be made]")
        create_symlinks(duplicates, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
