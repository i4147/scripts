import argparse
import re
import sys
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path
from typing import Any
from loguru import logger
from packaging import version as pkg_version

MAX_WORKERS = 8
WHEEL_EXTENSION = ".whl"
DEB_EXTENSION = ".deb"


def parse_wheel_version(filename):
    name = filename[:-4]
    parts = name.split("-")
    if len(parts) < 5:
        return None
    pkg_name_parts = []
    version_parts = []
    found_version = False
    for i, part in enumerate(parts):
        if not found_version and (re.match(r"^\d", part) or part.lower() in ["v", "ver", "version"]):
            found_version = True
            version_parts.append(part)
        elif not found_version:
            pkg_name_parts.append(part)
        else:
            remaining_parts = len(parts) - i
            if remaining_parts <= 3:
                break
            version_parts.append(part)
    if pkg_name_parts and version_parts:
        pkg_name = "-".join(pkg_name_parts)
        version = "-".join(version_parts)
        return pkg_name, version
    return None


def parse_deb_version(filename):
    name = filename[:-4]
    parts = name.split("_")
    if len(parts) >= 2:
        pkg_name = parts[0]
        version = parts[1]
        return pkg_name, version
    return None


def compare_versions(ver1, ver2):
    try:
        v1 = pkg_version.parse(ver1)
        v2 = pkg_version.parse(ver2)
        if v1 < v2:
            return -1
        elif v1 > v2:
            return 1
        else:
            return 0
    except Exception:
        if ver1 < ver2:
            return -1
        elif ver1 > ver2:
            return 1
        else:
            return 0


def process_file(path, file_type):
    try:
        filename = path.name
        if file_type == "wheel" and filename.endswith(WHEEL_EXTENSION):
            parsed = parse_wheel_version(filename)
            if parsed:
                pkg_name, version = parsed
                return pkg_name, version, path
        elif file_type == "deb" and filename.endswith(DEB_EXTENSION):
            parsed = parse_deb_version(filename)
            if parsed:
                pkg_name, version = parsed
                return pkg_name, version, path
    except Exception as e:
        logger.error(f"Error processing {path}: {e}")
    return None


def _process_file_wrapper(args):
    path, file_type = args
    return process_file(path, file_type)


def scan_directory(directory, file_type, check_all=False):
    packages = defaultdict(list)
    extensions = []
    if check_all:
        extensions = [WHEEL_EXTENSION, DEB_EXTENSION]
    elif file_type == "wheel":
        extensions = [WHEEL_EXTENSION]
    elif file_type == "deb":
        extensions = [DEB_EXTENSION]
    files_to_process = []
    for ext in extensions:
        files_to_process.extend(directory.rglob(f"*{ext}"))
    print(f"Found {len(files_to_process)} files to process...")
    tasks = []
    for path in files_to_process:
        if path.suffix == WHEEL_EXTENSION:
            tasks.append((path, "wheel"))
        elif path.suffix == DEB_EXTENSION:
            tasks.append((path, "deb"))
    with Pool(processes=MAX_WORKERS) as pool:
        async_results = [pool.apply_async(_process_file_wrapper, (task,)) for task in tasks]
        for async_result in async_results:
            result = async_result.get()
            if result:
                pkg_name, version, path = result
                packages[pkg_name].append((version, path))
    return packages


def get_latest_version(
    versions,
):
    if not versions:
        return None
    latest = versions[0]
    for version, path in versions[1:]:
        if compare_versions(version, latest[0]) > 0:
            latest = (version, path)
    return latest


def keep_latest_versions(packages, dry_run=False):
    total_deleted = 0
    for pkg_name, versions in packages.items():
        if len(versions) <= 1:
            continue
        latest = get_latest_version(versions)
        if latest is None:
            continue
        latest_version, latest_path = latest
        print(f"\nPackage: {pkg_name}")
        print(f"  Latest version: {latest_version} - {latest_path.name}")
        print(f"  Total versions found: {len(versions)}")
        for version, path in versions:
            if path == latest_path:
                continue
            if dry_run:
                print(f"  Would delete: {version} - {path.name}")
            else:
                try:
                    path.unlink()
                    print(f"  Deleted: {version} - {path.name}")
                    total_deleted += 1
                except Exception as e:
                    logger.error(f"  Error deleting {path.name}: {e}")
    return total_deleted


def main():
    parser = argparse.ArgumentParser(
        description="Detect and keep only the latest version of package files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-d", "--deb", action="store_true", help="Check .deb files")
    group.add_argument("-w", "--wheel", action="store_true", help="Check .whl files")
    group.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Check all package types (.whl and .deb)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate deletion without actually removing files",
    )
    parser.add_argument(
        "--dir",
        type=str,
        default=".",
        help="Directory to scan (default: current directory)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed information about each file",
    )
    args = parser.parse_args()
    if not (args.deb or args.wheel or args.all):
        args.wheel = True
    scan_dir = Path(args.dir).resolve()
    if not scan_dir.exists():
        logger.error(f"Error: Directory '{scan_dir}' does not exist")
        return 1
    if args.all:
        file_type = "all"
    elif args.deb:
        file_type = "deb"
    else:
        file_type = "wheel"
    print(f"Scanning directory: {scan_dir}")
    print(f"File type: {file_type}")
    if args.dry_run:
        print("DRY RUN MODE - No files will be deleted")
    print("-" * 40)
    packages = scan_directory(scan_dir, file_type, args.all)
    if not packages:
        print("No matching package files found.")
        return 0
    print(f"\nFound {len(packages)} package(s):")
    for pkg_name, versions in packages.items():
        print(f"  {pkg_name}: {len(versions)} version(s)")
        if args.verbose and len(versions) > 1:
            for version, path in versions:
                print(f"    - {version}: {path.name}")
    print("\n" + "=" * 40)
    total_deleted = keep_latest_versions(packages, args.dry_run)
    print("\n" + "=" * 40)
    if total_deleted == 0:
        print("No files to delete. All packages have only one version.")
    elif args.dry_run:
        print(f"Dry run complete. Would delete {total_deleted} file(s).")
    else:
        print(f"Cleanup complete. Deleted {total_deleted} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
