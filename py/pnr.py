import argparse
import os
import pathlib
import sys


def remove_string_from_filenames(string_to_remove, dry_run: bool = False) -> int:
    files = [f for f in os.listdir(".") if pathlib.Path(f).is_file()]
    renamed_count = 0
    for filename in files:
        if string_to_remove in filename:
            new_name = filename.replace(string_to_remove, "")
            if not new_name.strip():
                print(f"Warning: Removing '{string_to_remove}' would make filename empty for '{filename}'")
                continue
            if dry_run:
                print(f"Would rename: '{filename}' -> '{new_name}'")
            else:
                try:
                    pathlib.Path(filename).rename(new_name)
                    print(f"Renamed: '{filename}' -> '{new_name}'")
                    renamed_count += 1
                except OSError as e:
                    print(f"Error renaming '{filename}': {e}")
    return renamed_count


def replace_string_in_filenames(str1, str2, dry_run: bool = False) -> int:
    files = [f for f in os.listdir(".") if pathlib.Path(f).is_file()]
    renamed_count = 0
    for filename in files:
        if str1 in filename:
            new_name = filename.replace(str1, str2)
            if dry_run:
                print(f"Would rename: '{filename}' -> '{new_name}'")
            else:
                try:
                    pathlib.Path(filename).rename(new_name)
                    print(f"Renamed: '{filename}' -> '{new_name}'")
                    renamed_count += 1
                except OSError as e:
                    print(f"Error renaming '{filename}': {e}")
    return renamed_count


def rename_by_template(template, dry_run: bool = False) -> int:
    files = [f for f in os.listdir(".") if pathlib.Path(f).is_file()]
    script_name = pathlib.Path(__file__).name
    if script_name in files:
        files.remove(script_name)
    if not files:
        print("No files found to rename.")
        return 0
    file_count = len(files)
    if file_count < 10:
        padding = 1
    elif file_count < 100:
        padding = 2
    elif file_count < 1000:
        padding = 3
    else:
        padding = 4
    renamed_count = 0
    for i, filename in enumerate(files, 1):
        _name, ext = os.path.splitext(filename)
        number_str = str(i).zfill(padding)
        new_name = f"{template}{number_str}{ext}"
        if new_name == filename:
            continue
        if dry_run:
            print(f"Would rename: '{filename}' -> '{new_name}'")
        else:
            try:
                pathlib.Path(filename).rename(new_name)
                print(f"Renamed: '{filename}' -> '{new_name}'")
                renamed_count += 1
            except OSError as e:
                print(f"Error renaming '{filename}': {e}")
    return renamed_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rename files in current directory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pnr.py -r "old_string"
  python pnr.py -s whl zip
  python pnr.py -t myfile
  python pnr.py -t doc --dry-run
        """,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "-r",
        "--remove",
        metavar="STRING",
        help="Remove specified string from filenames",
    )
    group.add_argument(
        "-s",
        "--replace",
        nargs=2,
        metavar=("STR1", "STR2"),
        help="Replace STR1 with STR2 in filenames",
    )
    group.add_argument(
        "-t",
        "--template",
        metavar="NAME",
        help="Rename files using template with sequential numbering",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be renamed without actually doing it",
    )
    args = parser.parse_args()
    current_dir = pathlib.Path.cwd()
    print(f"Working in directory: {current_dir}")
    try:
        if args.remove:
            print(f"Removing '{args.remove}' from filenames...")
            count = remove_string_from_filenames(args.remove, args.dry_run)
            print(f"Operation completed. {count} files processed.")
        elif args.replace:
            str1, str2 = args.replace
            print(f"Replacing '{str1}' with '{str2}' in filenames...")
            count = replace_string_in_filenames(str1, str2, args.dry_run)
            print(f"Operation completed. {count} files processed.")
        elif args.template:
            print(f"Renaming files using template '{args.template}'...")
            count = rename_by_template(args.template, args.dry_run)
            print(f"Operation completed. {count} files processed.")
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
