import os
import sys
import re
import shutil


def extract_import_section(content):
    lines = content.split("\n")
    import_lines = []

    for line in lines:
        stripped = line.strip()

        if stripped and not stripped.startswith("#") and not stripped.startswith('"') and not stripped.startswith("'"):
            if stripped.startswith("import ") or stripped.startswith("from "):
                import_lines.append(line)
            else:
                if import_lines:
                    break
        else:
            if import_lines or (not stripped):
                import_lines.append(line)

    return "\n".join(import_lines)


def has_os_import(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        import_section = extract_import_section(content)

        patterns = [
            r"^import\s+os\b",
            r"^import\s+os\s+as\s+\w+",
            r"^from\s+os\s+import\s+",
        ]

        for line in import_section.split("\n"):
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                for pattern in patterns:
                    if re.search(pattern, stripped):
                        return True

        if re.search(r"^import\s+.*\bos\b", import_section, re.MULTILINE):
            return True

        return False

    except (UnicodeDecodeError, IOError) as e:
        print(f"Warning: Could not read {file_path}: {e}")
        return False


def get_python_files(root_dir):
    python_files = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.endswith(".py"):
                full_path = os.path.join(dirpath, filename)
                python_files.append(full_path)
    return python_files


def move_files(files, target_dir, root_dir):

    os.makedirs(target_dir, exist_ok=True)

    moved_files = []
    errors = []

    for file_path in files:
        rel_path = os.path.relpath(file_path, root_dir)

        target_path = os.path.join(target_dir, rel_path)
        target_subdir = os.path.dirname(target_path)

        try:
            os.makedirs(target_subdir, exist_ok=True)

            shutil.move(file_path, target_path)
            moved_files.append(rel_path)
            print(f"Moved: {rel_path} -> {target_path}")

        except Exception as e:
            errors.append((rel_path, str(e)))
            print(f"Error moving {rel_path}: {e}")

    return moved_files, errors


def main():

    root_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    target_dir = sys.argv[2] if len(sys.argv) > 2 else "has_os_import"

    if not os.path.isdir(root_dir):
        print(f"Error: '{root_dir}' is not a valid directory.")
        sys.exit(1)

    print(f"Scanning Python files in: {os.path.abspath(root_dir)}")
    print(f"Target subdirectory: {target_dir}")
    print("-" * 50)

    all_files = get_python_files(root_dir)
    print(f"Found {len(all_files)} Python files")

    files_to_move = []
    for file_path in all_files:
        if has_os_import(file_path):
            files_to_move.append(file_path)
            print(f"✓ {os.path.relpath(file_path, root_dir)}")

    print("-" * 50)
    print(f"Found {len(files_to_move)} files with 'import os'")

    if not files_to_move:
        print("No files to move.")
        return

    response = input(f"Move these {len(files_to_move)} files to '{target_dir}'? (y/n): ")
    if response.lower() != "y":
        print("Operation cancelled.")
        return

    print("\nMoving files...")
    moved, errors = move_files(files_to_move, target_dir, root_dir)

    print("-" * 50)
    print(f"Successfully moved {len(moved)} files")
    if errors:
        print(f"Errors: {len(errors)}")
        for file_path, error in errors:
            print(f"  {file_path}: {error}")


if __name__ == "__main__":
    main()
