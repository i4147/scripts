
import re
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import sys
import os
from typing import Optional

NEW_SHEBANG = "#!/data/data/com.termux/files/usr/bin/python"
SHEBANG_PATTERN = re.compile(r"^#!.*python[23]?(?:\.\d+)?(?:[ \t]+.*)?$", re.MULTILINE)


def is_symlink(path: Path) -> bool:
    return path.is_symlink() or os.path.islink(path)


def process_file(path: Path, root_dir: Path) -> tuple[Path, bool, Optional[str], str]:
    rel_path = str(path.relative_to(root_dir))
    if is_symlink(path):
        return (path, False, "Symlink skipped", rel_path)
    try:
        content = path.read_text(encoding="utf-8")
        if not content.startswith("#!"):
            return (path, False, "No shebang", rel_path)
        first_line = content.split("\n")[0] if "\n" in content else content
        if "python" not in first_line.lower():
            return (path, False, "Not a Python shebang", rel_path)
        if first_line.strip() == NEW_SHEBANG:
            return (path, False, "Already correct", rel_path)
        lines = content.split("\n")
        lines[0] = NEW_SHEBANG
        new_content = "\n".join(lines)
        path.write_text(new_content, encoding="utf-8")
        return (path, True, None, rel_path)
    except Exception as e:
        return (path, False, str(e), rel_path)


def find_python_files(directory: Path) -> list[Path]:
    python_files = []
    extensions = {".py", ".pyw", ".pyx", ".pxd", ".pyi"}
    for path in directory.rglob("*"):
        if ".git" in path.parts:
            continue
        if is_symlink(path):
            continue
        if path.is_file() and path.suffix in extensions:
            python_files.append(path)
        elif path.is_file() and path.stem and ("." not in path.name):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    first_line = f.readline()
                    if first_line.startswith("#!") and "python" in first_line.lower():
                        python_files.append(path)
            except (UnicodeDecodeError, IOError):
                pass
    return python_files


def main():
    current_dir = Path.cwd()
    print(f"📁 Scanning directory: {current_dir}")
    print("-" * 50)
    python_files = find_python_files(current_dir)
    if not python_files:
        print("No Python files found.")
        return
    print(f"Found {len(python_files)} Python files to check.")
    print("-" * 50)
    updated_files = []
    errors = []
    skipped_count = 0
    already_correct_count = 0
    with ProcessPoolExecutor() as executor:
        future_to_file = {executor.submit(process_file, path, current_dir): path for path in python_files}
        for future in as_completed(future_to_file):
            path, was_changed, error, rel_path = future.result()
            if error:
                if "Symlink" in error or "No shebang" in error or "Not a Python shebang" in error:
                    skipped_count += 1
                elif "Already correct" in error:
                    already_correct_count += 1
                else:
                    errors.append((rel_path, error))
            elif was_changed:
                updated_files.append((path, rel_path))
            else:
                skipped_count += 1
    if updated_files:
        print(f"\n✅ Updated {len(updated_files)} files:")
        print("-" * 50)
        for path, rel_path in updated_files:
            print(f"  {rel_path}")
    else:
        print("\n✅ No files needed updating.")
    print("\n" + "=" * 50)
    print(f"📊 Summary:")
    print(f"  ✅ Updated: {len(updated_files)} files")
    print(f"  ⏭️  Skipped: {skipped_count + already_correct_count} files")
    if errors:
        print(f"  ❌ Errors: {len(errors)} files")
    if errors:
        print("\n❌ Errors:")
        for rel_path, error in errors:
            print(f"  - {rel_path}: {error}")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
