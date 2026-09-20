import re
from pathlib import Path


def is_python_file(file_path: Path) -> bool:
    if file_path.suffix == ".py":
        return True
    if file_path.suffix == "":
        try:
            with Path(file_path).open(encoding="utf-8") as f:
                first_line = f.readline()
                if first_line.startswith("#!") and "python" in first_line.lower():
                    return True
        except (UnicodeDecodeError, PermissionError, IsADirectoryError):
            return False
    return False


def process_file(file_path: Path) -> bool | None:
    try:
        content = Path(file_path).read_text(encoding="utf-8")
        original_content = content
        pattern = "^(\\s*)import\\s+re\\s*($|#)"
        replacement = "\\1import regex as re\\2"
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
        if content != original_content:
            Path(file_path).write_text(content, encoding="utf-8")
            return True
        return False
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return False


def find_and_process_python_files(root_dir: str = ".") -> None:
    root_path = Path(root_dir)
    modified_files = []
    total_files = 0
    skip_dirs = {".git", ".svn", ".hg", "venv", "env", "__pycache__", "site-packages", "node_modules", ".venv", ".tox"}
    for item in root_path.rglob("*"):
        if item.is_dir():
            continue
        if any((part in skip_dirs or part.startswith(".") for part in item.parts)):
            continue
        if is_python_file(item):
            total_files += 1
            file_type = "(.py)" if item.suffix == ".py" else "(no ext)"
            print(f"Processing {file_type}: {item}")
            if process_file(item):
                modified_files.append(item)
                print("✓ Modified")
            else:
                print("  - No changes needed")
    print(f"  Total Python files processed: {total_files}")
    print(f"  Files modified: {len(modified_files)}")
    if modified_files:
        print("\nModified files:")
        for file in modified_files:
            print(f"  - {file}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Replace 'import re' with 'import regex as re' in Python files recursively."
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be changed without modifying files")
    parser.add_argument("directory", nargs="?", default=".", help="Directory to process (default: current directory)")
    args = parser.parse_args()
    print("processing '...")
    print(f"{Path(args.directory).resolve()}\n")
    if args.dry_run:
        print("\n*** DRY RUN MODE - No files will be modified ***\n")
    find_and_process_python_files(args.directory)
    print("\nDone!")


if __name__ == "__main__":
    main()
