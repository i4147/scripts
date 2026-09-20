import ast
import sys
from collections import deque
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

NEW_GET_FILES = """from collections import deque
def get_files(path: str | Path, ext: list[str] | None = None) -> list[Path]:
    path = Path(path)
    skip_dirs = {".git", "__pycache__"}
    queue = deque([path])
    files = []
    while queue:
        current = queue.popleft()
        try:
            entries = current.iterdir()
        except (PermissionError, OSError):
            continue
        for item in entries:
            if item.is_symlink():
                continue
            if item.is_dir() and item.name not in skip_dirs:
                queue.append(item)
            elif item.is_file():
                if ext is None or item.suffix in ext:
                    files.append(item)
    return files"""


def process_file(file_path: Path) -> tuple[Path, bool, str]:
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content)
    except Exception as e:
        return file_path, False, f"Parse error: {e}"

    get_files_start = None
    get_files_end = None
    skip_dirs_line = None

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_files":
            get_files_start = node.lineno - 1
            get_files_end = node.end_lineno
            break

    lines = content.split("\n")
    import_end = 0

    for i, line in enumerate(lines):
        if line.startswith(("import ", "from ")):
            import_end = i + 1

    for i, line in enumerate(lines):
        if "SKIP_DIRS" in line and "=" in line:
            skip_dirs_line = i
            break

    if get_files_start is None:
        return file_path, False, "get_files function not found"

    new_lines = lines[:import_end]
    new_lines.append("")
    new_lines.extend(NEW_GET_FILES.split("\n"))
    new_lines.append("")

    remaining_start = get_files_end

    if skip_dirs_line is not None and skip_dirs_line > import_end:
        new_lines.extend(lines[get_files_end:skip_dirs_line])
        remaining_start = skip_dirs_line + 1
        while remaining_start < len(lines) and not lines[remaining_start].strip():
            remaining_start += 1

    new_lines.extend(lines[remaining_start:])

    new_content = "\n".join(new_lines)

    try:
        ast.parse(new_content)
    except SyntaxError as e:
        return file_path, False, f"Validation failed: {e}"

    try:
        file_path.write_text(new_content, encoding="utf-8")
        return file_path, True, "Updated successfully"
    except Exception as e:
        return file_path, False, f"Write error: {e}"


def get_python_files(root: Path) -> list[Path]:
    skip_dirs = {".git", "__pycache__", ".venv", "venv", "node_modules"}
    queue = deque([root])
    files = []

    while queue:
        current = queue.popleft()
        try:
            entries = current.iterdir()
        except (PermissionError, OSError):
            continue

        for item in entries:
            if item.is_symlink():
                continue
            if item.is_dir() and item.name not in skip_dirs:
                queue.append(item)
            elif item.is_file() and item.suffix == ".py":
                files.append(item)

    return files


def main():
    root = Path.cwd()
    py_files = get_python_files(root)

    if not py_files:
        print("No Python files found")
        return

    print(f"Processing {len(py_files)} files...")

    with ProcessPoolExecutor() as executor:
        futures = {executor.submit(process_file, f): f for f in py_files}
        updated = 0
        failed = 0

        for future in as_completed(futures):
            file_path, success, message = future.result()
            status = "✓" if success else "✗"
            print(f"{status} {file_path.relative_to(root)}: {message}")

            if success:
                updated += 1
            else:
                failed += 1

    print(f"\nSummary: {updated} updated, {failed} failed")


if __name__ == "__main__":
    main()
