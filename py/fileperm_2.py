import os
import stat
from multiprocessing import Pool, cpu_count
from tqdm import tqdm
import argparse


SKIP_DIRS = {".git", ".ruff_cache", "__pycache__"}


def should_skip_dir(dirname):
    return dirname in SKIP_DIRS


def has_shebang(filepath):
    try:
        with open(filepath, "rb") as f:
            first_line = f.readline()
            return first_line.startswith(b"#!")
    except (OSError, IOError):
        return False


def get_file_permissions(filepath):
    try:
        return stat.S_IMODE(os.stat(filepath).st_mode)
    except:
        return None


def is_executable(filepath):
    try:
        return os.access(filepath, os.X_OK)
    except:
        return False


def determine_target_mode(filepath):

    if is_executable(filepath):
        return None

    parent_dir = os.path.basename(os.path.dirname(filepath))
    if has_shebang(filepath) or parent_dir == "bin":
        return 0o755

    return 0o644


def needs_chmod(filepath, target_mode):
    current_mode = get_file_permissions(filepath)
    if current_mode is None:
        return False
    return current_mode != target_mode


def chmod_file(args):
    filepath, target_mode = args
    try:
        os.chmod(filepath, target_mode)
        return True, filepath, None, target_mode
    except Exception as e:
        return False, filepath, str(e), target_mode


def collect_files(root_path="."):
    files_to_change = []
    files_to_skip = []
    files_make_executable = []
    all_files = 0
    skipped_dirs = set()

    print("Scanning files...")
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]

        original_dirs = set(os.listdir(dirpath)) if os.path.exists(dirpath) else set()
        current_dirs = set(dirnames)
        skipped_in_current = original_dirs.intersection(SKIP_DIRS)
        skipped_dirs.update(os.path.join(dirpath, d) for d in skipped_in_current)

        for filename in filenames:
            filepath = os.path.join(dirpath, filename)

            if os.path.islink(filepath):
                continue

            all_files += 1
            target_mode = determine_target_mode(filepath)

            if target_mode is None:
                files_to_skip.append(filepath)
                continue

            if needs_chmod(filepath, target_mode):
                files_to_change.append((filepath, target_mode))
                if target_mode == 0o755:
                    files_make_executable.append(filepath)

    return files_to_change, files_to_skip, files_make_executable, all_files, skipped_dirs


def process_files(root_path=".", num_workers=None):

    files_to_change, files_to_skip, files_make_executable, total_files, skipped_dirs = collect_files(root_path)

    print(f"\n{'=' * 60}")
    print(f"Scan Results:")
    print(f"  Skipped directories: {len(skipped_dirs)}")
    if skipped_dirs:
        for d in sorted(skipped_dirs)[:5]:
            print(f"    ⊘ {d}")
        if len(skipped_dirs) > 5:
            print(f"    ... and {len(skipped_dirs) - 5} more")
    print(f"  Total files found: {total_files}")
    print(f"  Already executable (skipped): {len(files_to_skip)}")
    print(f"  Will make executable (+x): {len(files_make_executable)}")
    print(f"  Will set to 0644: {len(files_to_change) - len(files_make_executable)}")
    print(f"  Total changes needed: {len(files_to_change)}")
    print(f"{'=' * 60}")

    if not files_to_change:
        print("\nAll files already have correct permissions!")
        return

    if num_workers is None:
        num_workers = min(cpu_count(), len(files_to_change))

    print(f"\nUsing {num_workers} workers\n")

    success_count = 0
    failed_count = 0
    failures = []
    made_executable = 0
    made_standard = 0

    with Pool(processes=num_workers) as pool:
        results = list(
            tqdm(
                pool.imap_unordered(chmod_file, files_to_change),
                total=len(files_to_change),
                desc="Changing permissions",
                unit="files",
                ncols=100,
            )
        )

    for success, filepath, error, mode in results:
        if success:
            success_count += 1
            if mode == 0o755:
                made_executable += 1
            else:
                made_standard += 1
        else:
            failed_count += 1
            failures.append((filepath, error))

    print(f"\n{'=' * 60}")
    print(f"Results:")
    print(f"  ✓ Made executable (0755): {made_executable}")
    print(f"  ✓ Set to standard (0644): {made_standard}")
    print(f"  ✓ Total successful: {success_count}")
    if failed_count > 0:
        print(f"  ✗ Failed: {failed_count}")
        print(f"\nFailures:")
        for filepath, error in failures[:10]:
            print(f"  - {filepath}: {error}")
        if len(failures) > 10:
            print(f"  ... and {len(failures) - 10} more failures")
    print(f"  ⊘ Skipped (already executable): {len(files_to_skip)}")
    print(f"{'=' * 60}")


def show_examples(files_to_change, files_to_skip, files_make_executable, num_examples=5):
    if files_make_executable:
        print(f"\nExamples of files to make executable (+x):")
        for f in files_make_executable[:num_examples]:
            print(f"  644 -> 755  {f}")
        if len(files_make_executable) > num_examples:
            print(f"  ... and {len(files_make_executable) - num_examples} more")

    standard_files = [f for f, m in files_to_change if m == 0o644]
    if standard_files:
        print(f"\nExamples of files to set to 0644:")
        for f in standard_files[:num_examples]:
            current = oct(get_file_permissions(f))
            print(f"  {current} -> 644  {f}")
        if len(standard_files) > num_examples:
            print(f"  ... and {len(standard_files) - num_examples} more")

    if files_to_skip:
        print(f"\nExamples of files skipped (already executable):")
        for f in files_to_skip[:num_examples]:
            print(f"  {f}")
        if len(files_to_skip) > num_examples:
            print(f"  ... and {len(files_to_skip) - num_examples} more")


def main():
    parser = argparse.ArgumentParser(
        description="Fix file permissions with smart rules using multiprocessing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Rules:
  - Files that are already executable: no changes
  - Files with shebang (#!) or in 'bin' directory: set to 0755
  - All other files: set to 0644

Skipped directories: {", ".join(sorted(SKIP_DIRS))}

Examples:
  %(prog)s                    # Process current directory
  %(prog)s /path/to/project   # Process specific path
  %(prog)s . -j 8             # Use 8 parallel workers
  %(prog)s . --dry-run        # Preview changes
  %(prog)s . --show-examples  # Show examples of changes
        """,
    )
    parser.add_argument("path", nargs="?", default=".", help="Root path to start from (default: current directory)")
    parser.add_argument(
        "-j", "--jobs", type=int, default=None, help="Number of parallel jobs (default: number of CPU cores)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be done without actually changing permissions"
    )
    parser.add_argument("--show-examples", action="store_true", help="Show example files that would be changed")

    args = parser.parse_args()

    print(f"Skip directories: {', '.join(sorted(SKIP_DIRS))}")

    if args.dry_run:
        print("DRY RUN - No changes will be made\n")
        files_to_change, files_to_skip, files_make_executable, total_files, skipped_dirs = collect_files(args.path)

        print(f"\n{'=' * 60}")
        print(f"Analysis Results:")
        print(f"  Skipped directories: {len(skipped_dirs)}")
        if skipped_dirs:
            for d in sorted(skipped_dirs)[:5]:
                print(f"    ⊘ {d}")
            if len(skipped_dirs) > 5:
                print(f"    ... and {len(skipped_dirs) - 5} more")
        print(f"  Total files: {total_files}")
        print(f"  Skip (already executable): {len(files_to_skip)}")
        print(f"  Make executable (+x): {len(files_make_executable)}")
        print(f"  Set to 0644: {len(files_to_change) - len(files_make_executable)}")
        print(f"  Total changes: {len(files_to_change)}")
        print(f"{'=' * 60}")

        if args.show_examples:
            show_examples(files_to_change, files_to_skip, files_make_executable)
    else:
        process_files(args.path, args.jobs)


if __name__ == "__main__":
    main()
