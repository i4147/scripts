from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dh import get_files
from packaging import version as pkg_version


def parse_wheel_version(filename: str) -> tuple[str, str] | None:
    if filename.endswith(".whl"):
        name = filename[:-4]
    if filename.endswith(".metadata"):
        name = filename[:-9]
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
        return (pkg_name, version)
    return None


def parse_targz_version(filename: str) -> tuple[str, str] | None:
    name = filename
    if filename.endswith(".tar.gz"):
        name = filename[:-7]
    elif filename.endswith(".tgz"):
        name = filename[:-4]
    else:
        return None
    parts = name.split("-")
    for i, part in enumerate(parts):
        if re.match(r"^\d", part):
            pkg_name = "-".join(parts[:i])
            version = "-".join(parts[i:])
            version = re.sub(r"\.(tar|tgz)$", "", version)
            if pkg_name and version:
                return (pkg_name, version)
    return None


def parse_deb_version(filename: str) -> tuple[str, str] | None:
    parts = filename.split("_")
    if len(parts) >= 2:
        pkg_name = parts[0]
        version = parts[1]
        return (pkg_name, version)
    return None


def compare_versions(ver1: str, ver2: str) -> int:
    try:
        v1 = pkg_version.parse(ver1)
        v2 = pkg_version.parse(ver2)
        if v1 < v2:
            return -1
        elif v1 > v2:
            return 1
        else:
            return 0
    except:
        if ver1 < ver2:
            return -1
        elif ver1 > ver2:
            return 1
        else:
            return 0


def process_file(file_path: Path, file_type: str) -> tuple[str, str, Path] | None:
    try:
        filename = file_path.name
        if file_type == "wheel" and filename.endswith((".whl", ".metadata")):
            parsed = parse_wheel_version(filename)
            if parsed:
                pkg_name, version = parsed
                return (pkg_name, version, file_path)
        elif file_type == "targz" and filename.endswith((".tar.gz", ".tgz")):
            parsed = parse_targz_version(filename)
            if parsed:
                pkg_name, version = parsed
                return (pkg_name, version, file_path)
        elif file_type == "deb" and filename.endswith(".deb"):
            parsed = parse_deb_version(filename)
            if parsed:
                pkg_name, version = parsed
                return (pkg_name, version, file_path)
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
    return None


def scan_directory(directory: Path, file_type: str, check_all: bool = False) -> dict[str, list[tuple[str, Path]]]:
    packages = defaultdict(list)
    extensions = (".whl", ".deb", ".tar.gz", ".tgz", ".metadata")
    if check_all:
        extensions = (".whl", ".deb", ".tar.gz", ".tgz", ".metadata")
    elif file_type == "wheel":
        extensions = (".whl", ".metadata")
    elif file_type == "deb":
        extensions = ".deb"
    elif file_type == "targz":
        extensions = (".tar.gz", ".tgz")
    files_to_process = get_files(directory, ext=extensions)
    print(f"Found {len(files_to_process)} files to process...")
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {}
        for file_path in files_to_process:
            if file_path.suffix in {".whl", ".metadata"}:
                future = executor.submit(process_file, file_path, "wheel")
            elif file_path.suffix == ".deb":
                future = executor.submit(process_file, file_path, "deb")
            elif (file_path.suffix == ".gz" and file_path.stem.endswith(".tar")) or file_path.suffix == ".tgz":
                future = executor.submit(process_file, file_path, "targz")
            else:
                continue
            futures[future] = file_path
        for future in as_completed(futures):
            result = future.result()
            if result:
                pkg_name, version, file_path = result
                packages[pkg_name].append((version, file_path))
    return packages


def get_latest_version(versions: list[tuple[str, Path]]) -> tuple[str, Path]:
    if not versions:
        return None
    latest = versions[0]
    for version, path in versions[1:]:
        if compare_versions(version, latest[0]) > 0:
            latest = (version, path)
    return latest


def keep_latest_versions(packages: dict[str, list[tuple[str, Path]]], dry_run: bool = False) -> tuple[int, int]:
    total_deleted = 0
    total_files_kept = 0
    for pkg_name, versions in packages.items():
        if len(versions) <= 1:
            total_files_kept += len(versions)
            continue
        latest_version, latest_path = get_latest_version(versions)
        print(f"\nPackage: {pkg_name}")
        print(f"  Latest version: {latest_version} - {latest_path.name}")
        print(f"  Total versions found: {len(versions)}")
        for version, file_path in versions:
            if file_path == latest_path:
                continue
            if dry_run:
                print(f"  Would delete: {version} - {file_path.name}")
            else:
                try:
                    file_path.unlink()
                    print(f"  Deleted: {version} - {file_path.name}")
                    total_deleted += 1
                except Exception as e:
                    print(f"  Error deleting {file_path.name}: {e}")
        total_files_kept += 1
    return (total_deleted, total_files_kept)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect and keep only the latest version of package files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\nExamples:\n  %(prog)s -w                # Clean wheel files only\n  %(prog)s -d                # Clean deb files only\n  %(prog)s -t                # Clean tar.gz files only\n  %(prog)s -a                # Clean all package types\n  %(prog)s -t --dry-run      # Preview what would be deleted\n        ",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-d", "--deb", action="store_true", help="Check .deb files")
    group.add_argument("-w", "--wheel", action="store_true", help="Check .whl files")
    group.add_argument("-t", "--targz", action="store_true", help="Check .tar.gz and .tgz files")
    group.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Check all package types (.whl, .deb, .tar.gz, .tgz)",
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
    if not (args.deb or args.wheel or args.targz or args.all):
        args.wheel = True
    scan_dir = Path(args.dir).resolve()
    if not scan_dir.exists():
        print(f"Error: Directory '{scan_dir}' does not exist")
        return 1
    if args.all:
        file_type = "all"
    elif args.deb:
        file_type = "deb"
    elif args.wheel:
        file_type = "wheel"
    elif args.targz:
        file_type = "targz"
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
    total_versions = sum(len(versions) for versions in packages.values())
    print(f"\nFound {len(packages)} package(s) with {total_versions} total version(s):")
    if args.verbose:
        for pkg_name, versions in packages.items():
            print(f"\n  {pkg_name}: {len(versions)} version(s)")
            for version, path in versions:
                print(f"    - {version}: {path.name}")
    else:
        for pkg_name, versions in packages.items():
            print(f"  {pkg_name}: {len(versions)} version(s)")
    print("\n" + "=" * 40)
    total_deleted, total_kept = keep_latest_versions(packages, args.dry_run)
    print("\n" + "=" * 40)
    if total_deleted == 0:
        print("No files to delete. All packages have only one version.")
    elif args.dry_run:
        print(f"Dry run complete. Would delete {total_deleted} file(s), keep {total_kept} file(s).")
    else:
        print(f"Cleanup complete. Deleted {total_deleted} file(s), kept {total_kept} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
