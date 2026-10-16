from __future__ import annotations

import logging
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

DEB_DIR = Path.home() / "debs"
EXCLUDED_PKGS = {
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
LOG_FILE = Path.home() / "make_deb.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def should_exclude(pkg_name: str) -> bool:
    pkg_lower = pkg_name.lower()
    if pkg_lower in EXCLUDED_PKGS:
        return True
    if any(exclude in pkg_lower for exclude in ["llvm", "clang"]):
        return True
    return bool(any(exclude in pkg_lower for exclude in ["rust", "cargo"]))


def get_installed_packages() -> list[str]:
    try:
        result = subprocess.run(["apt", "list", "--installed"], capture_output=True, text=True, check=True)
        packages = []
        for line in result.stdout.split("\n"):
            if "/" in line and "installed" in line:
                pkg_name = line.split("/")[0].strip()
                if not should_exclude(pkg_name):
                    packages.append(pkg_name)
        return sorted(packages)
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to get installed packages: {e}")
        return []


def create_deb_for_package(pkg_name: str) -> bool:
    try:
        DEB_DIR.mkdir(parents=True, exist_ok=True)
        deb_file = DEB_DIR / f"{pkg_name}.deb"
        if deb_file.exists():
            logger.info(f"✓ {pkg_name}.deb already exists, skipping...")
            return True
        logger.info(f"⟳ Creating .deb for {pkg_name}...")
        result = subprocess.run(
            ["apt", "download", pkg_name],
            capture_output=True,
            text=True,
            cwd=str(DEB_DIR),
        )
        if result.returncode != 0:
            logger.error(f"✗ Failed to download {pkg_name}: {result.stderr.strip()}")
            return False
        if deb_file.exists():
            logger.info(f"✓ Successfully created {pkg_name}.deb")
            return True
        else:
            logger.warning(f"⚠ Command succeeded but {pkg_name}.deb not found")
            return False
    except Exception as e:
        logger.error(f"✗ Error creating {pkg_name}.deb: {e}")
        return False


def process_packages(packages: list[str], max_workers: int = 4) -> tuple[int, int]:
    successful = 0
    failed = 0
    packages = [p for p in packages if not should_exclude(p)]
    if not packages:
        logger.warning("No packages to process (all excluded or empty list)")
        return 0, 0
    logger.info(f"Processing {len(packages)} packages with {max_workers} workers...")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_pkg = {executor.submit(create_deb_for_package, pkg): pkg for pkg in packages}
        for future in as_completed(future_to_pkg):
            pkg = future_to_pkg[future]
            try:
                if future.result():
                    successful += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"✗ Unexpected error for {pkg}: {e}")
                failed += 1
    return successful, failed


def main():
    if len(sys.argv) > 1:
        packages = sys.argv[1:]
        logger.info(f"Processing specified packages: {', '.join(packages)}")
    else:
        logger.info("Getting list of all installed packages...")
        packages = get_installed_packages()
        logger.info(f"Found {len(packages)} installed packages (after exclusions)")
    if not packages:
        logger.error("No packages to process")
        sys.exit(1)
    successful, failed = process_packages(packages)
    logger.info("=" * 40)
    logger.info(f"Summary: {successful} successful, {failed} failed")
    logger.info(f"Total: {successful + failed}")
    logger.info(f".deb files saved in: {DEB_DIR}")
    logger.info(f"Log file: {LOG_FILE}")
    if failed > 0:
        logger.warning(f"Some packages failed. Check {LOG_FILE} for details.")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    raise SystemExit(main())
