from __future__ import annotations

import argparse
import importlib.metadata
import logging
import site
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from pip._internal.commands.install import InstallCommand
from pip._internal.exceptions import InstallationError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(f"reinstall_entrypoint_packages_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def get_site_packages_dirs() -> list[Path]:
    site_dirs = []
    user_site = site.getusersitepackages()
    if user_site:
        site_dirs.append(Path(user_site))
    system_sites = site.getsitepackages()
    for s in system_sites:
        site_dirs.append(Path(s))
    seen = set()
    unique_dirs = []
    for d in site_dirs:
        if d.exists() and str(d) not in seen:
            seen.add(str(d))
            unique_dirs.append(d)
    return unique_dirs


def get_packages_with_entry_points() -> dict[str, dict[str, any]]:
    packages_with_eps = {}
    try:
        for dist in importlib.metadata.distributions():
            try:
                entry_points = dist.entry_points
                if not entry_points:
                    continue
                groups = set()
                if hasattr(entry_points, "select"):
                    for group in ["console_scripts", "gui_scripts"]:
                        eps = entry_points.select(group=group)
                        if eps:
                            groups.add(group)
                    all_groups = set()
                    if hasattr(entry_points, "groups"):
                        all_groups = set(entry_points.groups)
                    else:
                        for ep in entry_points:
                            if hasattr(ep, "group"):
                                all_groups.add(ep.group)
                    for group in all_groups:
                        if group not in ["console_scripts", "gui_scripts"]:
                            groups.add(group)
                else:
                    for ep in entry_points:
                        if hasattr(ep, "group"):
                            groups.add(ep.group)
                if groups:
                    metadata = dist.metadata
                    summary = metadata.get("Summary", "No summary") if metadata else "No summary"
                    packages_with_eps[dist.name] = {
                        "groups": groups,
                        "info": {
                            "version": dist.version,
                            "summary": summary,
                            "size": get_package_size(dist),
                        },
                    }
                    logger.debug(f"Found entry points in {dist.name}: {groups}")
            except Exception as e:
                logger.debug(f"Error checking entry points for {dist.name}: {e}")
    except Exception as e:
        logger.error(f"Error using importlib.metadata: {e}")
        return {}
    return packages_with_eps


def get_package_size(dist: importlib.metadata.Distribution) -> str:
    try:
        if hasattr(dist, "_path"):
            from pathlib import Path

            dist_path = Path(dist._path)
            if dist_path.exists() and dist_path.is_dir():
                total_size = 0
                for item in dist_path.rglob("*"):
                    if item.is_file():
                        total_size += item.stat().st_size
                if total_size > 1024 * 1024:
                    return f"{total_size / (1024 * 1024):.1f} MB"
                elif total_size > 1024:
                    return f"{total_size / 1024:.1f} KB"
                else:
                    return f"{total_size} B"
        return "Unknown"
    except Exception:
        return "Unknown"


def get_user_confirmation(package_name: str, package_data: dict, include_deps: bool = False) -> str:
    groups = package_data.get("groups", set())
    info = package_data.get("info", {})
    print("\n" + "=" * 40)
    print(f"📦 Package: {package_name}")
    print(f"   Version: {info.get('version', 'Unknown')}")
    print(f"   Entry points: {', '.join(groups)}")
    if info.get("summary") and info["summary"] != "No summary":
        print(f"   Summary: {info.get('summary', '')}")
    if info.get("size"):
        print(f"   Size: {info.get('size')}")
    if include_deps:
        print("   ⚠️  Will reinstall dependencies (may cause conflicts)")
    print("-" * 40)
    while True:
        response = input("Reinstall this package? (y/n/a/?) [y/n/a/?]: ").lower().strip()
        if response in ("y", "yes"):
            return "yes"
        elif response in ("n", "no"):
            return "no"
        elif response in ("a", "all"):
            return "all"
        elif response in ("?", "help"):
            print("\nOptions:")
            print("  y/yes  - Yes, reinstall this package")
            print("  n/no   - No, skip this package")
            print("  a/all  - Yes to all remaining packages")
            print("  ?/help - Show this help message")
            continue
        else:
            print("Invalid response. Please enter 'y', 'n', 'a', or '?'")
            continue


def reinstall_package_with_pip(package_name: str, include_deps: bool = False) -> tuple[str, bool, str]:
    try:
        install_cmd = InstallCommand()
        args = [
            "install",
            "--force-reinstall",
            "--no-cache-dir",
        ]
        if not include_deps:
            args.append("--no-deps")
        args.append(package_name)
        options, _ = install_cmd.parse_args(args)
        from pip._internal.utils.temp_dir import global_tempdir_manager

        with global_tempdir_manager():
            try:
                install_cmd.run(options, args)
                logger.info(f"✓ Successfully reinstalled: {package_name}")
                return (package_name, True, "Successfully reinstalled")
            except InstallationError as e:
                error_msg = str(e)
                logger.error(f"✗ Failed to reinstall {package_name}: {error_msg}")
                return (package_name, False, error_msg)
    except Exception as e:
        error_msg = str(e)
        logger.error(f"✗ Error reinstalling {package_name}: {error_msg}")
        return (package_name, False, error_msg)


def reinstall_entrypoint_packages(
    max_workers: int = 4,
    exclude_packages: set[str] | None = None,
    only_packages: set[str] | None = None,
    include_deps: bool = False,
    dry_run: bool = False,
    skip_confirmation: bool = False,
) -> None:
    if exclude_packages is None:
        exclude_packages = {"pip", "setuptools", "wheel"}
    entry_point_packages = get_packages_with_entry_points()
    if not entry_point_packages:
        logger.warning("No packages with entry points found!")
        return
    packages_to_reinstall = set(entry_point_packages.keys())
    packages_to_reinstall = packages_to_reinstall - exclude_packages
    if only_packages:
        packages_to_reinstall = packages_to_reinstall & only_packages
    logger.info(f"Found {len(entry_point_packages)} packages with entry points")
    logger.info(f"Will reinstall {len(packages_to_reinstall)} packages after filtering")
    if packages_to_reinstall:
        logger.info("\nPackages with entry points:")
        for i, pkg in enumerate(sorted(packages_to_reinstall), 1):
            data = entry_point_packages.get(pkg, {})
            groups = data.get("groups", set())
            version = data.get("info", {}).get("version", "Unknown")
            logger.info(f"  {i:3d}. {pkg} (v{version}) - entry points: {', '.join(groups)}")
    if dry_run:
        logger.info("\nDRY RUN - No packages will be reinstalled")
        return
    if not packages_to_reinstall:
        logger.warning("No packages to reinstall after filtering!")
        return
    if not skip_confirmation:
        selected_packages = set()
        all_selected = False
        for pkg in sorted(packages_to_reinstall):
            if all_selected:
                selected_packages.add(pkg)
                continue
            data = entry_point_packages.get(pkg, {})
            result = get_user_confirmation(pkg, data, include_deps)
            if result == "all":
                all_selected = True
                selected_packages.add(pkg)
            elif result == "yes":
                selected_packages.add(pkg)
        packages_to_reinstall = selected_packages
        if not packages_to_reinstall:
            logger.warning("No packages selected for reinstallation!")
            return
    else:
        logger.info("Skipping confirmation - will reinstall all packages")
    logger.info(f"\nStarting reinstallation of {len(packages_to_reinstall)} selected packages...")
    successful = []
    failed = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_package = {
            executor.submit(reinstall_package_with_pip, pkg, include_deps): pkg for pkg in packages_to_reinstall
        }
        for future in as_completed(future_to_package):
            package_name = future_to_package[future]
            try:
                name, success, message = future.result()
                if success:
                    successful.append(name)
                else:
                    failed.append((name, message))
            except Exception as e:
                logger.error(f"Unexpected error for {package_name}: {e}")
                failed.append((package_name, str(e)))
    logger.info("\n" + "=" * 40)
    logger.info("REINSTALLATION SUMMARY")
    logger.info("=" * 40)
    logger.info(f"✓ Successfully reinstalled: {len(successful)} packages")
    logger.info(f"✗ Failed to reinstall: {len(failed)} packages")
    if successful:
        logger.info("\nSuccessfully reinstalled packages:")
        for name in sorted(successful):
            logger.info(f"  ✓ {name}")
    if failed:
        logger.info("\nFailed packages:")
        for name, error in failed:
            logger.info(f"  ✗ {name}: {error[:100]}...")


def main():
    parser = argparse.ArgumentParser(
        description="Reinstall all Python packages with entry points using pip API",
        epilog="Compatible with Python 3.12+ and pip 26.1.2+",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)",
    )
    parser.add_argument(
        "-e",
        "--exclude",
        nargs="+",
        default=["pip", "setuptools", "wheel"],
        help="Packages to exclude from reinstallation",
    )
    parser.add_argument("-o", "--only", nargs="+", help="Only reinstall specified packages")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only show what would be reinstalled without actually doing it",
    )
    parser.add_argument(
        "--include-deps",
        action="store_true",
        help="Also reinstall dependencies (not recommended, may cause conflicts)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation and reinstall all packages (use with caution)",
    )
    args = parser.parse_args()
    if args.workers < 1:
        logger.error("Number of workers must be at least 1")
        sys.exit(1)
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    logger.info(f"Starting package reinstallation with {args.workers} workers")
    logger.info("Reinstalling ONLY packages with entry points (console_scripts, gui_scripts, etc.)")
    if args.yes:
        logger.warning("⚠️  Auto-confirmation enabled. Will reinstall all packages without prompting!")
    reinstall_entrypoint_packages(
        max_workers=args.workers,
        exclude_packages=set(args.exclude),
        only_packages=set(args.only) if args.only else None,
        include_deps=args.include_deps,
        dry_run=args.dry_run,
        skip_confirmation=args.yes,
    )


if __name__ == "__main__":
    raise SystemExit(main())
