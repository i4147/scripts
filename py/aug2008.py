import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

TARGET_DATE = datetime(2008, 8, 1).date()


def find_files_by_date(root: Path, target_date: datetime.date):
    for path in root.rglob("*"):
        if path.is_file():
            mtime = datetime.fromtimestamp(path.stat().st_mtime).date()
            if mtime == target_date:
                yield path


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete or move files with modification date 1 Aug 2008")
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan (default: current)",
    )
    parser.add_argument(
        "-m",
        "--move",
        action="store_true",
        help="Move matching files to a subdirectory named '2008' instead of deleting",
    )
    args = parser.parse_args()
    root_dir = Path(args.directory)
    if not root_dir.is_dir():
        print(f"Error: {root_dir} is not a directory")
        sys.exit(1)
    files_to_process = list(find_files_by_date(root_dir, TARGET_DATE))
    if not files_to_process:
        print("No files found with modification date 1 Aug 2008")
        return
    print(f"Found {len(files_to_process)} file(s) with date 1 Aug 2008:")
    for f in files_to_process:
        print(f)
    if args.move:
        dest_dir = root_dir / "2008"
        dest_dir.mkdir(exist_ok=True)
        confirm = input(f"Do you want to move these files to {dest_dir}? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return
        for f in files_to_process:
            try:
                shutil.move(str(f), dest_dir / f.name)
                print(f"Moved: {f} -> {dest_dir / f.name}")
            except Exception as e:
                print(f"Failed to move {f}: {e}")
    else:
        confirm = input("Do you really want to delete these files? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return
        for f in files_to_process:
            try:
                f.unlink()
                print(f"Deleted: {f}")
            except Exception as e:
                print(f"Failed to delete {f}: {e}")


if __name__ == "__main__":
    main()
