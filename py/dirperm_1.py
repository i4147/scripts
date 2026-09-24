import os
import stat
from multiprocessing import Pool, cpu_count
import argparse


def chmod_directory(dirpath):
    try:
        os.chmod(dirpath, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
        os.chmod(dirpath, 509)
        return (True, dirpath)
    except Exception as e:
        return (False, f"{dirpath}: {e}")


def collect_directories(root_path="."):
    directories = []
    for dirpath, dirnames, filenames in os.walk(root_path):
        directories.append(dirpath)
    return directories


def process_directories(root_path=".", num_workers=None):
    print(f"Collecting directories from: {os.path.abspath(root_path)}")
    directories = collect_directories(root_path)
    total_dirs = len(directories)
    print(f"Found {total_dirs} directories")
    if total_dirs == 0:
        print("No directories found.")
        return
    if num_workers is None:
        num_workers = min(cpu_count(), total_dirs)
    print(f"Using {num_workers} workers for processing")
    with Pool(processes=num_workers) as pool:
        results = pool.map(chmod_directory, directories)
    success_count = sum((1 for success, _ in results if success))
    failed_count = sum((1 for success, _ in results if not success))
    print(f"\nResults:")
    print(f"  Successful: {success_count}")
    print(f"  Failed: {failed_count}")
    if failed_count > 0:
        print("\nFirst 10 failures:")
        failures = [msg for success, msg in results if not success]
        for failure in failures[:10]:
            print(f"  - {failure}")
        if failed_count > 10:
            print(f"  ... and {failed_count - 10} more failures")


def main():
    parser = argparse.ArgumentParser(description="Recursively chmod all directories to 0775 using multiprocessing")
    parser.add_argument("path", nargs="?", default=".", help="Root path to start from (default: current directory)")
    parser.add_argument(
        "-j", "--jobs", type=int, default=None, help="Number of parallel jobs (default: number of CPU cores)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be done without actually changing permissions"
    )
    args = parser.parse_args()
    if args.dry_run:
        directories = collect_directories(args.path)
        print(f"Would chmod {len(directories)} directories to 0775")
        print("First 10 directories:")
        for d in directories[:10]:
            print(f"  {d}")
        if len(directories) > 10:
            print(f"  ... and {len(directories) - 10} more")
    else:
        process_directories(args.path, args.jobs)


if __name__ == "__main__":
    main()
