import json
import sys
import time

import requests
from dh import get_installed_packages
from packaging.version import InvalidVersion, Version


def check_package_on_pypi(package_name: str, current_version: str) -> str | None:
    try:
        time.sleep(0.01)
        url = f"https://pypi.org/pypi/{package_name}/json"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return data["info"]["version"]
        if response.status_code == 404:
            return None
        return None
    except requests.exceptions.RequestException as e:
        print(f"  ⚠️  Error checking {package_name}: {e}")
        return None
    except (KeyError, json.JSONDecodeError) as e:
        print(f"  ⚠️  Error parsing response for {package_name}: {e}")
        return None


def compare_versions(current: str, latest: str) -> str:
    try:
        current_v = Version(current)
        latest_v = Version(latest)
        if current_v < latest_v:
            return "update"
        if current_v > latest_v:
            return "newer"
    except InvalidVersion:
        if current == latest:
            return "current"
        if current < latest:
            return "update"
        return "newer"


def is_venv() -> bool:
    return hasattr(sys, "real_prefix") or (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix)


def main() -> None:
    if not is_venv():
        print("⚠️  Warning: Not running in a virtual environment!")
        response = input("Continue anyway? (y/N): ")
        if response.lower() != "y":
            print("Exiting.")
            return
    print("📦 Checking for package updates on PyPI...")
    print("(Results will appear as each package is checked)\n")
    installed = get_installed_packages()
    total_packages = len(installed)
    print(f"Processing {total_packages} packages:\n")
    updates_found = []
    errors = []
    up_to_date = 0
    for i, (package, current_version) in enumerate(sorted(installed.items()), 1):
        progress = f"[{i:3d}/{total_packages:3d}]"
        latest_version = check_package_on_pypi(package.lower(), current_version)
        if latest_version is None:
            print(f"{progress} {package:<30} : ⚠️  not found on PyPI")
            errors.append(package)
            continue
        status = compare_versions(current_version, latest_version)
        if status == "update":
            print(f"{progress} {package:<30} : 📦 update available from {current_version} to {latest_version}")
            updates_found.append((package, current_version, latest_version))
        elif status == "newer":
            print(
                f"{progress} {package:<30} : ⚠️  current version ({current_version}) is newer than PyPI ({latest_version})"
            )
            errors.append(package)
        else:
            print(f"{progress} {package:<30} : ✅ already latest version ({current_version})")
            up_to_date += 1
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total packages checked: {total_packages}")
    print(f"✅ Up to date: {up_to_date}")
    print(f"📦 Updates available: {len(updates_found)}")
    print(f"⚠️  Errors/Not found: {len(errors)}")
    if updates_found:
        print("\n" + "=" * 60)
        print("PACKAGES TO UPDATE")
        print("=" * 60)
        for package, current, latest in updates_found:
            print(f"  {package:<30} {current} -> {latest}")
        print("\n💡 To upgrade all packages, run:")
        packages_to_upgrade = [p[0] for p in updates_found]
        print(f"   python -m pip install --upgrade {' '.join(packages_to_upgrade)}")
        print("\n💡 To upgrade a specific package, run:")
        print("   python -m pip install --upgrade <package-name>")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Check interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)
