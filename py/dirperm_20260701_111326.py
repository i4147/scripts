import os
import stat
from multiprocessing import Pool, cpu_count
from tqdm import tqdm
import argparse


def needs_chmod(dirpath, target_mode=0o775):
    try:
        current_mode = stat.S_IMODE(os.stat(dirpath).st_mode)
        return current_mode != target_mode
    except (OSError, PermissionError):
        return False


def chmod_directory(args):
    dirpath, target_mode = args
    try:
        os.chmod(dirpath, target_mode)
        return True, dirpath, None
    except Exception as e:
        return False, dirpath, str(e)


def collect_directories_needing_change(root_path=".", target_mode=0o775):
    directories_to_change = []
    all_dirs = 0

    print("Scanning directories...")
    for dirpath, dirnames, filenames in os.walk(root_path):
        all_dirs += 1
        if needs_chmod(dirpath, target_mode):
            directories_to_change.append(dirpath)

    return directories_to_change, all_dirs


def process_directories(root_path=".", num_workers=None, target_mode=0o775):

    
    dirs_to_change, total_dirs = collect_directories_needing_change(root_path, target_mode)

    print(f"Total directories found: {total_dirs}")
    print(f"Directories needing change: {len(dirs_to_change)}")

    if not dirs_to_change:
        print("All directories already have correct permissions!")
        return

    
    if num_workers is None:
        num_workers = min(cpu_count(), len(dirs_to_change))

    print(f"Using {num_workers} workers\n")

    
    args = [(d, target_mode) for d in dirs_to_change]

    
    success_count = 0
    failed_count = 0
    failures = []

    with Pool(processes=num_workers) as pool:
        
        results = list(
            tqdm(
                pool.imap_unordered(chmod_directory, args),
                total=len(dirs_to_change),
                desc="Changing permissions",
                unit="dirs",
                ncols=100,
            )
        )

    
    for success, dirpath, error in results:
        if success:
            success_count += 1
        else:
            failed_count += 1
            failures.append((dirpath, error))

    
    print(f"\n{'=' * 50}")
    print(f"Results:")
    print(f"  ✓ Successfully changed: {success_count}")
    if failed_count > 0:
        print(f"  ✗ Failed: {failed_count}")
        print(f"\nFailures:")
        for dirpath, error in failures[:10]:
            print(f"  - {dirpath}: {error}")
        if len(failures) > 10:
            print(f"  ... and {len(failures) - 10} more failures")
    print(f"{'=' * 50}")


def main():
    parser = argparse.ArgumentParser(
        description="Recursively chmod directories to 0775 using multiprocessing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Process current directory
  %(prog)s /path/to/dir       # Process specific path
  %(prog)s . -j 8             # Use 8 parallel workers
  %(prog)s . -m 0750          # Use different permission mode
  %(prog)s . --dry-run        # Preview changes
        """,
    )
    parser.add_argument("path", nargs="?", default=".", help="Root path to start from (default: current directory)")
    parser.add_argument(
        "-j", "--jobs", type=int, default=None, help="Number of parallel jobs (default: number of CPU cores)"
    )
    parser.add_argument("-m", "--mode", type=str, default="0775", help="Permission mode in octal (default: 0775)")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be done without actually changing permissions"
    )
    parser.add_argument(
        "--show-current", action="store_true", help="Show current permissions of directories that need changes"
    )

    args = parser.parse_args()

    
    try:
        target_mode = int(args.mode, 8)
    except ValueError:
        print(f"Error: Invalid permission mode '{args.mode}'. Use octal format (e.g., 0775)")
        return

    if args.dry_run:
        print(f"DRY RUN - No changes will be made")
        print(f"Target mode: {args.mode}\n")

        dirs_to_change, total_dirs = collect_directories_needing_change(args.path, target_mode)
        print(f"Total directories: {total_dirs}")
        print(f"Would change: {len(dirs_to_change)} directories")

        if args.show_current and dirs_to_change:
            print(f"\nDirectories needing changes:")
            for d in dirs_to_change[:20]:
                try:
                    current = oct(stat.S_IMODE(os.stat(d).st_mode))
                    print(f"  {current} -> {args.mode}  {d}")
                except:
                    print(f"  ??? -> {args.mode}  {d}")
            if len(dirs_to_change) > 20:
                print(f"  ... and {len(dirs_to_change) - 20} more")
    else:
        process_directories(args.path, args.jobs, target_mode)


if __name__ == "__main__":
    main()
