import sys
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final
import apt  
import apt.package  
from loguru import logger
DEB_DIR = Path.home() / "debs"
LOG_FILE = Path.home() / "make_deb.log"
MAX_WORKERS = 8
EXCLUDED_PKGS = frozenset(
    {
        "llvm",
        "clang",
        "libllvm",
        "libclang",
        "rust",
        "cargo",
        "lld",
        "lldb",
        "compiler-rt",
        "libc++",
        "libc++abi",
        "rust-stdlib",
        "rust-analyzer",
        "cargo-c",
    }
)
logger.remove()
logger.add(sys.stderr, level="INFO")
logger.add(
    LOG_FILE, level="INFO", format="{time:YYYY-MM-DD HH:mm:ss} - {level} - {message}"
)
def should_exclude(pkg_name):
    pkg_lower = pkg_name.lower()
    if pkg_lower in EXCLUDED_PKGS:
        return True
    if any(exclude in pkg_lower for exclude in ("llvm", "clang")):
        return True
    return any(exclude in pkg_lower for exclude in ("rust", "cargo"))
def get_installed_packages():
    try:
        cache = apt.Cache()
        packages = [
            pkg.name
            for pkg in cache
            if pkg.is_installed and not should_exclude(pkg.name)
        ]
        return sorted(packages)
    except Exception as exc:
        logger.error(f"Failed to get installed packages: {exc}")
        return []
def create_deb_for_package(pkg_name):
    try:
        DEB_DIR.mkdir(parents=True, exist_ok=True)
        deb_file = DEB_DIR / f"{pkg_name}.deb"
        if deb_file.exists():
            print(f"✓ {pkg_name}.deb already exists, skipping...")
            return True
        cache = apt.Cache()
        if pkg_name not in cache:
            logger.error(f"✗ Package {pkg_name} not found in apt cache")
            return False
        pkg = cache[pkg_name]
        candidate = pkg.candidate
        if candidate is None:
            logger.error(f"✗ No candidate version available for {pkg_name}")
            return False
        print(f"⟳ Creating .deb for {pkg_name}...")
        result_path = candidate.fetch_binary(dest_dir=str(DEB_DIR))
        if result_path and Path(result_path).exists():
            print(f"✓ Successfully created {pkg_name}.deb")
            return True
        if deb_file.exists():
            print(f"✓ Successfully created {pkg_name}.deb")
            return True
        logger.warning(f"⚠ Fetch returned no file for {pkg_name}")
        return False
    except Exception as exc:
        logger.error(f"✗ Error creating {pkg_name}.deb: {exc}")
        return False
def process_packages(packages):
    successful = 0
    failed = 0
    filtered = [p for p in packages if not should_exclude(p)]
    if not filtered:
        logger.warning("No packages to process (all excluded or empty list)")
        return 0, 0
    print(f"Processing {len(filtered)} packages with {MAX_WORKERS} workers...")
    with Pool(processes=MAX_WORKERS) as pool:
        async_results = [
            pool.apply_async(create_deb_for_package, (pkg,)) for pkg in filtered
        ]
        for pkg, async_res in zip(filtered, async_results):
            try:
                if async_res.get():
                    successful += 1
                else:
                    failed += 1
            except Exception as exc:
                logger.error(f"✗ Unexpected error for {pkg}: {exc}")
                failed += 1
    return successful, failed
def main():
    if len(sys.argv) > 1:
        packages = sys.argv[1:]
        print(f"Processing specified packages: {', '.join(packages)}")
    else:
        print("Getting list of all installed packages...")
        packages = get_installed_packages()
        print(f"Found {len(packages)} installed packages (after exclusions)")
    if not packages:
        logger.error("No packages to process")
        sys.exit(1)
    successful, failed = process_packages(packages)
    print("=" * 40)
    print(f"Summary: {successful} successful, {failed} failed")
    print(f"Total: {successful + failed}")
    print(f".deb files saved in: {DEB_DIR}")
    print(f"Log file: {LOG_FILE}")
    if failed > 0:
        logger.warning(f"Some packages failed. Check {LOG_FILE} for details.")
    sys.exit(0 if failed == 0 else 1)
if __name__ == "__main__":
    raise SystemExit(main())
