import argparse
import os
import sys
from pathlib import Path


def get_unique_name(path, base_name: str):
    if not Path(os.path.join(path, base_name)).exists():
        return base_name
    name, ext = os.path.splitext(base_name)
    counter = 1
    while True:
        new_name = f"{name}_{counter}{ext}"
        if not Path(os.path.join(path, new_name)).exists():
            return new_name
        counter += 1


def ask_user_for_rename(old_name: str, new_name: str):
    return True
    while True:
        response = (
            input(f"'{new_name}' already exists. Rename '{old_name}' with _number suffix? (y/n): ").lower().strip()
        )
        if response in {"y", "yes"}:
            return True
        if response in {"n", "no"}:
            return False
        print("Please enter 'y' or 'n'")


def remove_string_from_names(
    string_to_remove,
    dry_run=False,
    recursive=False,
    current_path: str = ".",
) -> int:
    renamed_count = 0
    try:
        items = os.listdir(current_path)
    except PermissionError:
        print(f"Permission denied: {current_path}")
        return renamed_count
    files = []
    dirs = []
    for item in items:
        item_path = os.path.join(current_path, item)
        if Path(item_path).is_file():
            files.append(item)
        elif Path(item_path).is_dir():
            dirs.append(item)
    for filename in files:
        if string_to_remove in filename:
            new_name = filename.replace(string_to_remove, "")
            if not new_name.strip():
                print(f"Warning: Removing '{string_to_remove}' would make filename empty for '{filename}'")
                continue
            old_path = os.path.join(current_path, filename)
            new_path = os.path.join(current_path, new_name)
            if Path(new_path).exists():
                if dry_run:
                    print(f"Would conflict: '{filename}' -> '{new_name}' (already exists)")
                elif ask_user_for_rename(filename, new_name):
                    new_name = get_unique_name(
                        current_path,
                        new_name,
                    )
                    new_path = os.path.join(current_path, new_name)
                else:
                    print(f"Skipped: '{filename}'")
                    continue
            if dry_run:
                print(f"Would rename: '{old_path}' -> '{new_name}'")
            else:
                try:
                    Path(old_path).rename(new_path)
                    print(f"{old_path} -> {new_name}")
                    renamed_count += 1
                except OSError as e:
                    print(f"Error renaming '{filename}': {e}")
    dirs_to_process = []
    for dirname in dirs:
        if string_to_remove in dirname:
            new_name = dirname.replace(string_to_remove, "")
            if not new_name.strip():
                print(f"Warning: Removing '{string_to_remove}' would make dirname empty for '{dirname}'")
                dirs_to_process.append((dirname, dirname))
                continue
            old_path = os.path.join(current_path, dirname)
            new_path = os.path.join(current_path, new_name)
            if Path(new_path).exists():
                if dry_run:
                    print(f"Would conflict: '{dirname}' -> '{new_name}' (already exists)")
                    dirs_to_process.append((dirname, dirname))
                elif ask_user_for_rename(dirname, new_name):
                    new_name = get_unique_name(
                        current_path,
                        new_name,
                    )
                    new_path = os.path.join(current_path, new_name)
                else:
                    print(f"Skipped: '{dirname}'")
                    dirs_to_process.append((dirname, dirname))
                    continue
            if dry_run:
                print(f"Would rename: '{old_path}' -> '{new_name}'")
                dirs_to_process.append((dirname, dirname))
            else:
                try:
                    Path(old_path).rename(new_path)
                    print(f"{old_path} -> {new_name}")
                    renamed_count += 1
                    dirs_to_process.append((new_name, new_name))
                except OSError as e:
                    print(f"Error renaming '{dirname}': {e}")
                    dirs_to_process.append((dirname, dirname))
        else:
            dirs_to_process.append((dirname, dirname))
    if recursive:
        for _, dirname in dirs_to_process:
            subdir_path = os.path.join(current_path, dirname)
            renamed_count += remove_string_from_names(
                string_to_remove,
                dry_run,
                recursive,
                subdir_path,
            )
    return renamed_count


def replace_string_in_names(
    str1,
    str2,
    dry_run=False,
    recursive=False,
    current_path: str = ".",
) -> int:
    renamed_count = 0
    try:
        items = os.listdir(current_path)
    except PermissionError:
        print(f"Permission denied: {current_path}")
        return renamed_count
    files = []
    dirs = []
    for item in items:
        item_path = os.path.join(current_path, item)
        if Path(item_path).is_file():
            files.append(item)
        elif Path(item_path).is_dir():
            dirs.append(item)
    for filename in files:
        if str1 in filename:
            new_name = filename.replace(str1, str2)
            old_path = os.path.join(current_path, filename)
            new_path = os.path.join(current_path, new_name)
            if Path(new_path).exists():
                if dry_run:
                    print(f"Would conflict: '{filename}' -> '{new_name}' (already exists)")
                elif ask_user_for_rename(filename, new_name):
                    new_name = get_unique_name(
                        current_path,
                        new_name,
                    )
                    new_path = os.path.join(current_path, new_name)
                else:
                    print(f"Skipped: '{filename}'")
                    continue
            if dry_run:
                print(f"Would rename: '{old_path}' -> '{new_name}'")
            else:
                try:
                    Path(old_path).rename(new_path)
                    print(f"{old_path} -> {new_name}")
                    renamed_count += 1
                except OSError as e:
                    print(f"Error renaming '{filename}': {e}")
    dirs_to_process = []
    for dirname in dirs:
        if str1 in dirname:
            new_name = dirname.replace(str1, str2)
            old_path = os.path.join(current_path, dirname)
            new_path = os.path.join(current_path, new_name)
            if Path(new_path).exists():
                if dry_run:
                    print(f"Would conflict: '{dirname}' -> '{new_name}' (already exists)")
                    dirs_to_process.append((dirname, dirname))
                elif ask_user_for_rename(dirname, new_name):
                    new_name = get_unique_name(
                        current_path,
                        new_name,
                    )
                    new_path = os.path.join(current_path, new_name)
                else:
                    print(f"Skipped: '{dirname}'")
                    dirs_to_process.append((dirname, dirname))
                    continue
            if dry_run:
                print(f"Would rename: '{old_path}' -> '{new_name}'")
                dirs_to_process.append((dirname, dirname))
            else:
                try:
                    Path(old_path).rename(new_path)
                    print(f"{old_path} -> {new_name}")
                    renamed_count += 1
                    dirs_to_process.append((new_name, new_name))
                except OSError as e:
                    print(f"Error renaming '{dirname}': {e}")
                    dirs_to_process.append((dirname, dirname))
        else:
            dirs_to_process.append((dirname, dirname))
    if recursive:
        for _, dirname in dirs_to_process:
            subdir_path = os.path.join(current_path, dirname)
            renamed_count += replace_string_in_names(
                str1,
                str2,
                dry_run,
                recursive,
                subdir_path,
            )
    return renamed_count


def rename_by_template(
    template,
    dry_run=False,
    recursive=False,
    current_path: str = ".",
) -> int:
    renamed_count = 0
    try:
        items = os.listdir(current_path)
    except PermissionError:
        print(f"Permission denied: {current_path}")
        return renamed_count
    files = [f for f in items if Path(os.path.join(current_path, f)).is_file()]
    script_name = Path(__file__).name
    if script_name in files:
        files.remove(script_name)
    if not files:
        print(f"No files found to rename in {current_path}.")
    else:
        file_count = len(files)
        if file_count < 10:
            padding = 1
        elif file_count < 100:
            padding = 2
        elif file_count < 1000:
            padding = 3
        else:
            padding = 4
        for i, filename in enumerate(files, 1):
            _name, ext = os.path.splitext(filename)
            number_str = str(i).zfill(padding)
            new_name = f"{template}{number_str}{ext}"
            if new_name == filename:
                continue
            old_path = os.path.join(current_path, filename)
            new_path = os.path.join(current_path, new_name)
            if Path(new_path).exists():
                if dry_run:
                    print(f"Would conflict: '{filename}' -> '{new_name}' (already exists)")
                elif ask_user_for_rename(filename, new_name):
                    new_name = get_unique_name(
                        current_path,
                        new_name,
                    )
                    new_path = os.path.join(current_path, new_name)
                else:
                    print(f"Skipped: '{filename}'")
                    continue
            if dry_run:
                print(f"Would rename: '{old_path}' -> '{new_name}'")
            else:
                try:
                    np = Path(new_path)
                    new_path = get_unique_name(np.parent, np.name)
                    Path(old_path).rename(new_path)
                    print(f"{old_path} -> {new_name}")
                    renamed_count += 1
                except OSError as e:
                    print(f"Error renaming '{filename}': {e}")
    if recursive:
        dirs = [d for d in items if Path(os.path.join(current_path, d)).is_dir()]
        for dirname in dirs:
            subdir_path = os.path.join(current_path, dirname)
            renamed_count += rename_by_template(
                template,
                dry_run,
                recursive,
                subdir_path,
            )
    return renamed_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rename files and directories",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pnr.py -r "old_string"
        """,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "-r",
        "--remove",
        metavar="STRING",
        help="Remove specified string from file and directory names",
    )
    group.add_argument(
        "-s",
        "--replace",
        nargs=2,
        metavar=("STR1", "STR2"),
        help="Replace STR1 with STR2 in file and directory names",
    )
    group.add_argument(
        "-t",
        "--template",
        metavar="NAME",
        default="",
        help="Rename files using template with sequential numbering",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be renamed without actually doing it",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Process directories recursively",
    )
    args = parser.parse_args()
    current_dir = Path.cwd()
    print(f"Working in directory: {current_dir}")
    if args.recursive:
        print("Recursive mode enabled")
    if args.dry_run:
        print("DRY RUN MODE - No actual changes will be made\n")
    try:
        if args.remove:
            print(f"Removing '{args.remove}' from names...")
            count = remove_string_from_names(
                args.remove,
                args.dry_run,
                args.recursive,
            )
            print(f"\nOperation completed. {count} items processed.")
        elif args.replace:
            str1, str2 = args.replace
            print(f"Replacing '{str1}' with '{str2}' in names...")
            count = replace_string_in_names(
                str1,
                str2,
                args.dry_run,
                args.recursive,
            )
            print(f"\nOperation completed. {count} items processed.")
        elif args.template:
            print(f"Renaming files using template '{args.template}'...")
            count = rename_by_template(
                args.template,
                args.dry_run,
                args.recursive,
            )
            print(f"\nOperation completed. {count} items processed.")
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
