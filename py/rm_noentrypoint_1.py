
import argparse
import zipfile
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final

from loguru import logger

MAX_WORKERS: Final[int] = 8

WheelCheck = tuple[Path, bool]


def check_wheel_for_entry_points(wheel_path: Path) -> WheelCheck:
    try:
        with zipfile.ZipFile(wheel_path, "r") as wheel:
            for name in wheel.namelist():
                if name.endswith(".dist-info/entry_points.txt"):
                    return wheel_path, True
            return wheel_path, False
    except (zipfile.BadZipFile, OSError) as exc:
        logger.error(f"Error reading {wheel_path.name}: {exc}")
        return wheel_path, False


def find_wheel_files(directory: Path = Path.cwd()) -> list[Path]:
    return sorted(directory.glob("*.whl"))


def remove_wheels_without_entry_points(
    directory: Path = Path.cwd(),
    dry_run: bool = False,
) -> None:
    wheel_files: list[Path] = find_wheel_files(directory)
    if not wheel_files:
        logger.info("No .whl files found in the current directory.")
        return

    logger.info(f"Found {len(wheel_files)} wheel file(s) to check...")

    wheels_to_remove: list[Path] = []
    wheels_to_keep: list[Path] = []

    with Pool(processes=MAX_WORKERS) as pool:
        async_results: list[AsyncResult[WheelCheck]] = [
            pool.apply_async(check_wheel_for_entry_points, (wheel,)) for wheel in wheel_files
        ]
        for async_res in async_results:
            wheel_path, has_entry_points = async_res.get()
            if has_entry_points:
                wheels_to_keep.append(wheel_path)
                logger.info(f"✓ {wheel_path.name} - has entry_points.txt (keeping)")
            else:
                wheels_to_remove.append(wheel_path)
                logger.info(f"✗ {wheel_path.name} - no entry_points.txt (removing)")

    logger.info("=" * 40)
    logger.info(f"Results: {len(wheels_to_keep)} to keep, {len(wheels_to_remove)} to remove")

    if not wheels_to_remove:
        logger.info("No files to remove.")
        return

    if dry_run:
        logger.info("[DRY RUN] Would remove the following files:")
        for wheel in wheels_to_remove:
            logger.info(f"  - {wheel.name}")
        return

    logger.info("Removing files without entry_points.txt...")
    for wheel in wheels_to_remove:
        try:
            wheel.unlink()
            logger.info(f"  Removed: {wheel.name}")
        except OSError as exc:
            logger.error(f"  Error removing {wheel.name}: {exc}")


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Remove .whl wheel files without entry_points.txt"
    )
    parser.add_argument(
        "-d",
        "--directory",
        type=Path,
        default=Path.cwd(),
        help="Directory to search for .whl files (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be removed without actually removing files",
    )
    args: argparse.Namespace = parser.parse_args()

    if not args.directory.exists():
        logger.error(f"Directory '{args.directory}' does not exist.")
        return

    remove_wheels_without_entry_points(directory=args.directory, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
