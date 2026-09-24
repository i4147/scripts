import argparse
import multiprocessing
import re
import sys
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from dh import get_files
from loguru import logger
from packaging import version as pkg_version

POOL_WORKERS = 8
WHEEL_EXTENSIONS = (".whl", ".metadata")
TARGZ_EXTENSIONS = (".tar.gz", ".tgz")
DEB_EXTENSIONS = (".deb",)
ALL_EXTENSIONS = (
    ".whl",
    ".metadata",
    ".deb",
    ".tar.gz",
    ".tgz",
)
ParsedEntry = tuple[str, str, Path]
VersionEntry = tuple[str, Path]
PackageMap = dict[str, list[VersionEntry]]


def parse_wheel_version(filename):
    if filename.endswith(".whl"):
        name = filename[:-4]
    elif filename.endswith(".metadata"):
        name = filename[:-9]
    else:
        return None
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


def parse_targz_version(filename):
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


def parse_deb_version(filename):
    parts = filename.split("_")
    if len(parts) >= 2:
        pkg_name = parts[0]
        version = parts[1]
        return (pkg_name, version)
    return None


def compare_versions(ver1, ver2):
    try:
        v1 = pkg_version.parse(ver1)
        v2 = pkg_version.parse(ver2)
        if v1 < v2:
            return -1
        if v1 > v2:
            return 1
        return 0
    except Exception:
        if ver1 < ver2:
            return -1
        if ver1 > ver2:
            return 1
        return 0


def process_file(path, file_type):
    try:
        filename = path.name
        if file_type == "wheel" and filename.endswith(WHEEL_EXTENSIONS):
            parsed = parse_wheel_version(filename)
            if parsed:
                pkg_name, version = parsed
                return (pkg_name, version, path)
        elif file_type == "targz" and filename.endswith(TARGZ_EXTENSIONS):
            parsed = parse_targz_version(filename)
            if parsed:
                pkg_name, version = parsed
                return (pkg_name, version, path)
        elif file_type == "deb" and filename.endswith(DEB_EXTENSIONS):
            parsed = parse_deb_version(filename)
            if parsed:
                pkg_name, version = parsed
                return (pkg_name, version, path)
    except Exception as e:
        logger.error(f"Error processing {path}: {e}")
    return None


def _resolve_file_type(path):
    if path.suffix in {".whl", ".metadata"}:
        return "wheel"
    if path.suffix == ".deb":
        return "deb"
    if (path.suffix == ".gz" and path.stem.endswith(".tar")) or (path.suffix == ".tgz"):
        return "targz"
    return None


def _process_entry(path):
    file_type = _resolve_file_type(path)
    if file_type is None:
        return None
    return process_file(path, file_type)


def _select_extensions(file_type, check_all):
    if check_all or file_type == "all":
        return ALL_EXTENSIONS
    if file_type == "wheel":
        return WHEEL_EXTENSIONS
    if file_type == "deb":
        return DEB_EXTENSIONS
    if file_type == "targz":
        return TARGZ_EXTENSIONS
    return WHEEL_EXTENSIONS


def scan_directory(directory, file_type, check_all=False):
    packages = defaultdict(list)
    extensions = _select_extensions(file_type, check_all)
    files_to_process = get_files(directory, ext=extensions)
    files_list = list(files_to_process)
    print(f"Found {len(files_list)} files to process...")
    if not files_list:
        return packages
    with multiprocessing.Pool(processes=POOL_WORKERS) as pool:
        async_results = [(pool.apply_async(_process_entry, (path,)), path) for path in files_list]
        for async_result, path in async_results:
            try:
                result = async_result.get()
            except Exception as e:
                logger.error(f"Error processing {path}: {e}")
                continue
            if result:
                pkg_name, version, parsed_path = result
                packages[pkg_name].append((version, parsed_path))
    return packages


def get_latest_version(versions):
    if not versions:
        return None
    latest = versions[0]
    for version, path in versions[1:]:
        if compare_versions(version, latest[0]) > 0:
            latest = (version, path)
    return latest


def keep_latest_versions(packages, dry_run=False):
    total_deleted = 0
    total_files_kept = 0
    for pkg_name, versions in packages.items():
        if len(versions) <= 1:
            total_files_kept += len(versions)
            continue
        latest = get_latest_version(versions)
        if latest is None:
            continue
        latest_version, latest_path = latest
        print(f"Package: {pkg_name}")
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
        total_files_kept += 1
    return (total_deleted, total_files_kept)


def _build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Detect and keep only the latest version of package files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "\nExamples:\n"
            "  %(prog)s -w                # Clean wheel files only\n"
            "  %(prog)s -d                # Clean deb files only\n"
            "  %(prog)s -t                # Clean tar.gz files only\n"
            "  %(prog)s -a                # Clean all package types\n"
            "  %(prog)s -t --dry-run      # Preview what would be deleted\n"
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-d", "--deb", action="store_true", help="Check .deb files")
    group.add_argument("-w", "--wheel", action="store_true", help="Check .whl files")
    group.add_argument(
        "-t",
        "--targz",
        action="store_true",
        help="Check .tar.gz and .tgz files",
    )
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
    return parser


def main():
    parser = _build_arg_parser()
    args = parser.parse_args()
    if not (args.deb or args.wheel or args.targz or args.all):
        args.wheel = True
    scan_dir = Path(args.dir).resolve()
    if not scan_dir.exists():
        logger.error(f"Directory '{scan_dir}' does not exist")
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
