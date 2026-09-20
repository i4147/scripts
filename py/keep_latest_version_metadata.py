from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from packaging.version import InvalidVersion, Version


def parse_filename(filepath: Path) -> tuple[str, Version, Path]:
    name = filepath.stem
    match = re.match(r"^(.+?)-(\d[\d._]*[a-zA-Z]*[\d]*)$", name)
    if not match:
        print(f"Warning: Could not parse version from {filepath.name}")
        return (name, Version("0.0.0"), filepath)
    pkg_name = match.group(1)
    version_str = match.group(2)
    normalized_version = version_str.replace("_", ".")
    try:
        version = Version(normalized_version)
    except InvalidVersion:
        print(f"Warning: Invalid version '{version_str}' in {filepath.name}")
        version = Version("0.0.0")
    return (pkg_name.lower(), version, filepath)


def normalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def find_metadata_files(directory: Path) -> list[Path]:
    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")
    return list(directory.glob("*.metadata"))


def process_file_batch(files: list[Path]) -> dict[str, list[tuple[Version, Path]]]:
    packages = defaultdict(list)
    for filepath in files:
        pkg_name, version, path = parse_filename(filepath)
        normalized_name = normalize_package_name(pkg_name)
        packages[normalized_name].append((version, path))
    return packages


def find_old_versions(package_files: list[tuple[Version, Path]]) -> list[Path]:
    if len(package_files) <= 1:
        return []
    sorted_files = sorted(package_files, key=lambda x: x[0], reverse=True)
    latest = sorted_files[0]
    old_versions = sorted_files[1:]
    print(f"  Keeping: {latest[1].name} (v{latest[0]})")
    for version, path in old_versions:
        print(f"  Removing: {path.name} (v{version})")
    return [path for version, path in old_versions]


def merge_results(
    results: list[dict[str, list[tuple[Version, Path]]]],
) -> dict[str, list[tuple[Version, Path]]]:
    merged = defaultdict(list)
    for result in results:
        for pkg_name, versions in result.items():
            merged[pkg_name].extend(versions)
    return merged


def delete_files(paths: list[Path], dry_run: bool = True, backup_dir: Path | None = None):
    for path in paths:
        if dry_run:
            print(f"  [DRY RUN] Would delete: {path.name}")
        elif backup_dir:
            backup_path = backup_dir / path.name
            shutil.move(str(path), str(backup_path))
            print(f"  Moved to backup: {path.name}")
        else:
            path.unlink()
            print(f"  Deleted: {path.name}")


def main():
    parser = argparse.ArgumentParser(description="Remove old versions of Python package metadata files")
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory containing metadata files (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting",
    )
    parser.add_argument(
        "--backup-dir",
        type=str,
        help="Move old files to backup directory instead of deleting",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of worker processes (default: CPU count)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of files to process per batch (default: 100)",
    )
    args = parser.parse_args()
    metadata_dir = Path(args.directory)
    if not metadata_dir.exists():
        print(f"Error: Directory '{metadata_dir}' does not exist")
        return 1
    backup_dir = None
    if args.backup_dir:
        backup_dir = Path(args.backup_dir)
        if not args.dry_run:
            backup_dir.mkdir(parents=True, exist_ok=True)
    print(f"Scanning directory: {metadata_dir}")
    all_files = find_metadata_files(metadata_dir)
    print(f"Found {len(all_files)} metadata files")
    if not all_files:
        print("No metadata files found")
        return 0
    batch_size = max(1, args.batch_size)
    batches = [all_files[i : i + batch_size] for i in range(0, len(all_files), batch_size)]
    print(f"Processing {len(batches)} batches using {args.workers or 'all available'} workers...")
    batch_results = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        future_to_batch = {executor.submit(process_file_batch, batch): i for i, batch in enumerate(batches)}
        for future in as_completed(future_to_batch):
            batch_idx = future_to_batch[future]
            try:
                result = future.result()
                batch_results.append(result)
                print(f"  Batch {batch_idx + 1}/{len(batches)} completed")
            except Exception as e:
                print(f"  Error processing batch {batch_idx + 1}: {e}")
    print("\nMerging results...")
    all_packages = merge_results(batch_results)
    print(f"\nProcessing {len(all_packages)} unique packages...")
    files_to_delete = []
    for pkg_name, versions in sorted(all_packages.items()):
        if len(versions) > 1:
            print(f"\nPackage: {pkg_name} ({len(versions)} versions)")
            old_files = find_old_versions(versions)
            files_to_delete.extend(old_files)
    print(f"\n{'=' * 40}")
    print("Summary:")
    print(f"  Total metadata files: {len(all_files)}")
    print(f"  Unique packages: {len(all_packages)}")
    print(f"  Files to remove: {len(files_to_delete)}")
    if files_to_delete:
        print(f"\n{'=' * 40}")
        print(f"Removing {len(files_to_delete)} old version files...")
        delete_files(files_to_delete, dry_run=args.dry_run, backup_dir=backup_dir)
        if args.dry_run:
            print("\nThis was a dry run. Use without --dry-run to actually delete files.")
    else:
        print("\nNo duplicate versions found. All packages have single versions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
