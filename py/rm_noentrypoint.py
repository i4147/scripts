from __future__ import annotations

import argparse
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


def check_wheel_for_entry_points(wheel_path: Path) -> tuple[Path, bool]:
    try:
        with zipfile.ZipFile(wheel_path, "r") as wheel:
            for name in wheel.namelist():
                if name.endswith(".dist-info/entry_points.txt"):
                    return wheel_path, True
            return wheel_path, False
    except (zipfile.BadZipFile, OSError) as e:
        print(f"Error reading {wheel_path.name}: {e}")
        return wheel_path, False


def find_wheel_files(directory: Path = Path.cwd()) -> list[Path]:
    return list(directory.glob("*.whl"))


def remove_wheels_without_entry_points(
    directory: Path = Path.cwd(), max_workers: int | None = None, dry_run: bool = False
) -> None:
    wheel_files = find_wheel_files(directory)
    if not wheel_files:
        print("No .whl files found in the current directory.")
        return
    print(f"Found {len(wheel_files)} wheel file(s) to check...")
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_wheel = {executor.submit(check_wheel_for_entry_points, wheel): wheel for wheel in wheel_files}
        wheels_to_remove = []
        wheels_to_keep = []
        for future in as_completed(future_to_wheel):
            wheel_path, has_entry_points = future.result()
            if has_entry_points:
                wheels_to_keep.append(wheel_path)
                print(f"✓ {wheel_path.name} - has entry_points.txt (keeping)")
            else:
                wheels_to_remove.append(wheel_path)
                print(f"✗ {wheel_path.name} - no entry_points.txt (removing)")
    print(f"\n{'=' * 40}")
    print(f"Results: {len(wheels_to_keep)} to keep, {len(wheels_to_remove)} to remove")
    if wheels_to_remove:
        if dry_run:
            print("\n[DRY RUN] Would remove the following files:")
            for wheel in wheels_to_remove:
                print(f"  - {wheel.name}")
        else:
            print("\nRemoving files without entry_points.txt...")
            for wheel in wheels_to_remove:
                try:
                    wheel.unlink()
                    print(f"  Removed: {wheel.name}")
                except OSError as e:
                    print(f"  Error removing {wheel.name}: {e}")
    else:
        print("\nNo files to remove.")


def main():
    parser = argparse.ArgumentParser(description="Remove .whl wheel files without entry_points.txt")
    parser.add_argument(
        "-d",
        "--directory",
        type=Path,
        default=Path.cwd(),
        help="Directory to search for .whl files (default: current directory)",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=None,
        help="Maximum number of parallel workers (default: CPU count)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be removed without actually removing files",
    )
    args = parser.parse_args()
    if not args.directory.exists():
        print(f"Error: Directory '{args.directory}' does not exist.")
        return
    remove_wheels_without_entry_points(directory=args.directory, max_workers=args.workers, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
