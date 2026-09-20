import argparse
import shutil
import site
from multiprocessing import Pool
from pathlib import Path
from typing import Any
from loguru import logger
DEFAULT_OUTPUT_DIR = Path("~/tmp/pkgs").expanduser()
NUM_WORKERS = 8
def get_site_packages_paths():
    paths = []
    for path_str in site.getsitepackages():
        paths.append(Path(path_str))
    user_site = site.getusersitepackages()
    if user_site:
        user_path = Path(user_site)
        if user_path.exists():
            paths.append(user_path)
    return paths
def get_package_path(package_name, site_paths):
    for site_path in site_paths:
        pkg_path = site_path / package_name
        if pkg_path.exists() and pkg_path.is_dir():
            return pkg_path
        alt_name = package_name.replace("-", "_")
        pkg_path = site_path / alt_name
        if pkg_path.exists() and pkg_path.is_dir():
            return pkg_path
        for item in site_path.iterdir():
            if item.is_dir() and item.name.lower().replace(
                "-", "_"
            ) == package_name.lower().replace("-", "_"):
                return item
    return None
def copy_package(
    args_tuple,
):
    package_name, output_dir, site_paths = args_tuple
    try:
        pkg_path = get_package_path(package_name, site_paths)
        if not pkg_path:
            return package_name, False, "Package directory not found"
        dest_path = output_dir / package_name
        if dest_path.exists():
            shutil.rmtree(dest_path)
        dest_path.mkdir(parents=True)
        for path in pkg_path.rglob("*"):
            if path.suffix == ".pyc":
                continue
            rel_path = path.relative_to(pkg_path)
            dest_file = dest_path / rel_path
            if path.is_dir():
                dest_file.mkdir(parents=True, exist_ok=True)
            else:
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest_file)
        return package_name, True, f"Copied to {dest_path}"
    except Exception as e:
        return package_name, False, f"Error: {e!s}"
def main():
    parser = argparse.ArgumentParser(
        description="Copy installed Python packages into separate folders under ~/tmp/pkgs/<pkgname>"
    )
    parser.add_argument(
        "packages",
        nargs="+",
        help="Names of packages to copy",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Output base directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    args = parser.parse_args()
    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {output_dir}")
    site_paths = get_site_packages_paths()
    print(f"Site-packages paths: {[str(p) for p in site_paths]}")
    process_args = [(pkg, output_dir, site_paths) for pkg in args.packages]
    successful = []
    failed = []
    with Pool(processes=NUM_WORKERS) as pool:
        async_results = [pool.apply_async(copy_package, (arg,)) for arg in process_args]
        total = len(async_results)
        for idx, async_result in enumerate(async_results, 1):
            pkg_name, success, message = async_result.get()
            if success:
                successful.append((pkg_name, message))
                print(f"[{idx}/{total}] ✓ {pkg_name}: {message}")
            else:
                failed.append((pkg_name, message))
                logger.error(f"[{idx}/{total}] ✗ {pkg_name}: {message}")
    print("\n" + "=" * 40)
    print("SUMMARY")
    print("=" * 40)
    print(f"Total packages processed: {len(process_args)}")
    print(f"✓ Successfully copied: {len(successful)}")
    print(f"✗ Failed: {len(failed)}")
    if failed:
        logger.error("\nFailed packages:")
        for pkg, msg in failed:
            logger.error(f"  ✗ {pkg}: {msg}")
    return 1 if failed else 0
if __name__ == "__main__":
    raise SystemExit(main())
