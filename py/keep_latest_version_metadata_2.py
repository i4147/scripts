import argparse
import re
import shutil
import sys
from collections import defaultdict
from collections.abc import Iterable
from multiprocessing import Pool
from pathlib import Path
from loguru import logger
from packaging.version import InvalidVersion, Version

WORKER_COUNT = 8
DEFAULT_BATCH_SIZE = 100
DEFAULT_VERSION = Version("0.0.0")
FILENAME_PATTERN = re.compile(r"^(.+?)-(\d[\d._]*[a-zA-Z]*[\d]*)$")
NORMALIZE_PATTERN = re.compile(r"[-_.]+")
VersionedPath = tuple[Version, Path]
PackageMap = dict[str, list[VersionedPath]]


def parse_filename(path):
    name = path.stem
    match = FILENAME_PATTERN.match(name)
    if not match:
        logger.warning(f"Could not parse version from {path.name}")
        return (name.lower(), DEFAULT_VERSION, path)
    pkg_name = match.group(1)
    version_str = match.group(2)
    normalized_version = version_str.replace("_", ".")
    try:
        version = Version(normalized_version)
    except InvalidVersion:
        logger.warning(f"Invalid version '{version_str}' in {path.name}")
        version = DEFAULT_VERSION
    return (pkg_name.lower(), version, path)


def normalize_package_name(name):
    return NORMALIZE_PATTERN.sub("-", name).lower()


def find_metadata_files(directory):
    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")
    return list(directory.glob("*.metadata"))


def process_file_batch(files):
    packages = defaultdict(list)
    for path in files:
        pkg_name, version, path = parse_filename(path)
        normalized_name = normalize_package_name(pkg_name)
        packages[normalized_name].append((version, path))
    return dict(packages)


def find_old_versions(package_files):
    if len(package_files) <= 1:
        return []
    sorted_files = sorted(package_files, key=lambda x: x[0], reverse=True)
    latest = sorted_files[0]
    old_versions = sorted_files[1:]
    print(f"  Keeping: {latest[1].name} (v{latest[0]})")
    for version, path in old_versions:
        print(f"  Removing: {path.name} (v{version})")
    return [path for _version, path in old_versions]


def merge_results(results):
    merged = defaultdict(list)
    for result in results:
        for pkg_name, versions in result.items():
            merged[pkg_name].extend(versions)
    return dict(merged)


def delete_files(
    paths,
    dry_run=True,
    backup_dir=None,
):
    for path in paths:
        if dry_run:
            print(f"  [DRY RUN] Would delete: {path.name}")
        elif backup_dir is not None:
            backup_path = backup_dir / path.name
            shutil.move(str(path), str(backup_path))
            print(f"  Moved to backup: {path.name}")
        else:
            path.unlink()
            print(f"  Deleted: {path.name}")


def parse_args(argv=None):
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
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Number of files to process per batch (default: {DEFAULT_BATCH_SIZE})",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    metadata_dir = Path(args.directory)
    if not metadata_dir.exists():
        logger.error(f"Directory '{metadata_dir}' does not exist")
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
    print(f"Processing {len(batches)} batches using {WORKER_COUNT} workers...")
    batch_results = []
    with Pool(processes=WORKER_COUNT) as pool:
        async_results = [pool.apply_async(process_file_batch, (batch,)) for batch in batches]
        for idx, async_result in enumerate(async_results):
            try:
                result = async_result.get()
                batch_results.append(result)
                print(f"  Batch {idx + 1}/{len(batches)} completed")
            except Exception as e:
                logger.exception(f"  Error processing batch {idx + 1}: {e}")
    print("Merging results...")
    all_packages = merge_results(batch_results)
    print(f"Processing {len(all_packages)} unique packages...")
    files_to_delete = []
    for pkg_name, versions in sorted(all_packages.items()):
        if len(versions) > 1:
            print(f"Package: {pkg_name} ({len(versions)} versions)")
            old_files = find_old_versions(versions)
            files_to_delete.extend(old_files)
    print("=" * 40)
    print("Summary:")
    print(f"  Total metadata files: {len(all_files)}")
    print(f"  Unique packages: {len(all_packages)}")
    print(f"  Files to remove: {len(files_to_delete)}")
    if files_to_delete:
        print("=" * 40)
        print(f"Removing {len(files_to_delete)} old version files...")
        delete_files(files_to_delete, dry_run=args.dry_run, backup_dir=backup_dir)
        if args.dry_run:
            print("This was a dry run. Use without --dry-run to actually delete files.")
    else:
        print("No duplicate versions found. All packages have single versions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
