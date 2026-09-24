import re
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import sys
from typing import Optional


NEW_SHEBANG = "#!/data/data/com.termux/files/usr/bin/env python"


SHEBANG_PATTERN = re.compile(r"^#!.*python[23]?(?:\.\d+)?(?:[ \t]+.*)?$", re.MULTILINE)


def process_file(file_path: Path) -> tuple[Path, bool, Optional[str]]:
    try:
        content = file_path.read_text(encoding="utf-8")

        if not content.startswith("#!"):
            return file_path, False, None

        first_line = content.split("\n")[0] if "\n" in content else content
        if "python" not in first_line.lower():
            return file_path, False, None

        if first_line.strip() == NEW_SHEBANG:
            return file_path, False, None

        lines = content.split("\n")
        lines[0] = NEW_SHEBANG
        new_content = "\n".join(lines)

        file_path.write_text(new_content, encoding="utf-8")
        return file_path, True, None

    except Exception as e:
        return file_path, False, str(e)


def find_python_files(directory: Path) -> list[Path]:
    python_files = []

    extensions = {".py", ".pyw", ".pyx", ".pxd", ".pyi"}

    for file_path in directory.rglob("*"):
        if file_path.is_file() and file_path.suffix in extensions:
            python_files.append(file_path)

        elif file_path.is_file() and file_path.stem and "." not in file_path.name:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    first_line = f.readline()
                    if first_line.startswith("#!") and "python" in first_line.lower():
                        python_files.append(file_path)
            except (UnicodeDecodeError, IOError):
                pass

    return python_files


def main():
    current_dir = Path.cwd()

    print(f"Searching for Python files in: {current_dir}")

    python_files = find_python_files(current_dir)

    if not python_files:
        print("No Python files found.")
        return

    print(f"Found {len(python_files)} Python files.")

    changed_files = []
    errors = []
    skipped_files = []

    with ProcessPoolExecutor() as executor:
        future_to_file = {executor.submit(process_file, file_path): file_path for file_path in python_files}

        for future in as_completed(future_to_file):
            file_path, was_changed, error = future.result()

            if error:
                errors.append((file_path, error))
            elif was_changed:
                changed_files.append(file_path)
            else:
                skipped_files.append(file_path)

    print("\n" + "=" * 50)
    print(f"✅ Changed: {len(changed_files)} files")
    print(f"⏭️  Skipped: {len(skipped_files)} files (no change needed)")
    print(f"❌ Errors: {len(errors)} files")

    if changed_files:
        print("\nChanged files:")
        for file_path in changed_files[:10]:
            print(f"  - {file_path}")
        if len(changed_files) > 10:
            print(f"  ... and {len(changed_files) - 10} more")

    if errors:
        print("\nErrors:")
        for file_path, error in errors[:5]:
            print(f"  - {file_path}: {error}")
        if len(errors) > 5:
            print(f"  ... and {len(errors) - 5} more")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
