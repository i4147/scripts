import argparse
import concurrent.futures
import csv
import fnmatch
import importlib.metadata
import os
import shutil
import site
import sys
from pathlib import Path


def get_user_site_path() -> Path:
    if not site.USER_SITE:
        site.main()
    return Path(site.USER_SITE).resolve()


def get_matching_packages(pattern: str) -> list[str]:
    matching = []
    for dist in importlib.metadata.distributions():
        name = dist.metadata["Name"]
        if fnmatch.fnmatch(name.lower(), pattern.lower()):
            matching.append(name)
    return matching


def resolve_package_list(patterns: list[str]) -> tuple[list[str], list[str]]:
    matched_packages = []
    unmatched_patterns = []

    for pattern in patterns:
        if any(c in pattern for c in "*?[]"):
            matches = get_matching_packages(pattern)
            if matches:
                matched_packages.extend(matches)
            else:
                unmatched_patterns.append(pattern)
        else:
            matched_packages.append(pattern)

    return matched_packages, unmatched_patterns


def copy_single_file(record_row: list[str], dist_location: Path, target_dir: Path) -> bool:
    if not record_row:
        return False
    relative_path_str = record_row[0]
    source_file = (dist_location / relative_path_str).resolve()
    if not source_file.is_file():
        return False
    if not source_file.is_relative_to(dist_location):
        return False
    destination_file = target_dir / relative_path_str
    destination_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source_file, destination_file)
        return True
    except Exception as e:
        print(f"   ❌ Error copying {relative_path_str}: {e}")
        return False


def process_package(pkg_name: str, user_site: Path, base_target_dir: Path) -> str:
    try:
        dist = importlib.metadata.distribution(pkg_name)
    except importlib.metadata.PackageNotFoundError:
        return f"❌ Package '{pkg_name}' is not installed in this environment."
    dist_location = Path(dist.locate_file("")).resolve()
    if not dist_location.is_relative_to(user_site):
        return f"ℹ️  Package '{pkg_name}' found, but it is not installed in the user site folder (Location: {dist_location}). Skipping."
    record_file = dist.locate_file(f"{dist.name}-{dist.version}.dist-info/RECORD")
    record_path = Path(record_file)
    if not record_path.is_file():
        return f"❌ Package '{pkg_name}' found in user-site, but its 'RECORD' file is missing. Cannot map files."
    pkg_target_dir = base_target_dir / pkg_name
    pkg_target_dir.mkdir(parents=True, exist_ok=True)
    try:
        with record_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            records = list(reader)
    except Exception as e:
        return f"❌ Failed to parse RECORD file for '{pkg_name}': {e}"
    copied_count = 0
    with concurrent.futures.ThreadPoolExecutor() as file_executor:
        futures = [file_executor.submit(copy_single_file, row, dist_location, pkg_target_dir) for row in records]
        for future in concurrent.futures.as_completed(futures):
            if future.result():
                copied_count += 1
    return f"✅ Package '{pkg_name}' completely extracted! Copied {copied_count} files to {pkg_target_dir}"


def main():
    parser = argparse.ArgumentParser(
        description="Extract installed user-site Python packages to ~/tmp/pkgs/<pkgname>",
        epilog="Examples:\n"
        "  python script.py requests              # Extract exact package\n"
        '  python script.py "req*"                 # Extract packages starting with "req"\n'
        '  python script.py "django-*"             # Extract all django-related packages\n'
        '  python script.py "flask" "sql*"         # Extract flask and all sql-packages',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "patterns", nargs="+", help='Package names or wildcard patterns (e.g., "a*" for all packages starting with "a")'
    )
    parser.add_argument("--list-only", action="store_true", help="Only list matching packages without extracting")
    args = parser.parse_args()

    matched_packages, unmatched_patterns = resolve_package_list(args.patterns)

    seen = set()
    matched_packages = [x for x in matched_packages if not (x in seen or seen.add(x))]

    if unmatched_patterns:
        print(f"⚠️  No packages found matching: {', '.join(unmatched_patterns)}")

    if not matched_packages:
        print("❌ No matching packages found.")
        return

    user_site = get_user_site_path()
    base_target_dir = Path.home() / "tmp" / "pkgs"
    print(f"🔍 System User-Site Path: {user_site}")
    print(f"📁 Destination Folder:   {base_target_dir}")
    print(f"📦 Found {len(matched_packages)} matching package(s):")
    for pkg in matched_packages:
        print(f"   - {pkg}")
    print("-" * 60)

    if args.list_only:
        return

    with concurrent.futures.ThreadPoolExecutor() as pkg_executor:
        future_to_pkg = {
            pkg_executor.submit(process_package, pkg, user_site, base_target_dir): pkg for pkg in matched_packages
        }
        for future in concurrent.futures.as_completed(future_to_pkg):
            pkg_name = future_to_pkg[future]
            try:
                result_message = future.result()
                print(result_message)
            except Exception as exc:
                print(f"❌ Package '{pkg_name}' generated an unhandled exception: {exc}")


if __name__ == "__main__":
    main()
