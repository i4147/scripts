import re
from pathlib import Path


def replace_multiprocessing_patterns(content: str):
    replacements = [
        (
            r"from concurrent.futures import ProcessPoolExecutor, as_completed\b",
            r"from multiprocessing import get_context",
        ),
        (
            r"import concurrent.futures\b",
            r"import multiprocessing",
        ),
        (
            r"with (Process|Thread)PoolExecutor\((.*?)\) as (\w+):",
            r"with Pool(8) as pool:",
        ),
        (
            r"with (Process|Thread)PoolExecutor\((.*?)\) as (\w+):",
            r"with Pool(8) as pool:",
        ),
        (
            r"(\w+) = (Process|Thread)PoolExecutor\((.*?)\)",
            r"pool = Pool(8)",
        ),
        (
            r"(\w+)\s*=\s*(Process|Thread)PoolExecutor\((.*?)\)",
            r"pool = Pool(8)",
        ),
    ]
    modified_content = content
    for pattern, replacement in replacements:
        modified_content = re.sub(pattern, replacement, modified_content)
    return modified_content


def process_python_file(file_path: Path) -> bool:
    try:
        original_content = Path(file_path).read_text(encoding="utf-8")
        if "multiprocessing" not in original_content:
            return False
        modified_content = replace_multiprocessing_patterns(original_content)
        if modified_content != original_content:
            Path(file_path).write_text(modified_content, encoding="utf-8")
            print(f"✓ Modified: {file_path}")
            return True
        return False
    except Exception as e:
        print(f"✗ Error processing {file_path}: {e}")
        return False


def find_and_replace_in_directory(directory: str = ".") -> None:
    directory_path = Path(directory)
    python_files = list(directory_path.rglob("*.py"))
    if not python_files:
        print("No Python files found.")
        return
    print(f"Found {len(python_files)} Python file(s). Processing...\n")
    modified_count = 0
    for py_file in python_files:
        if process_python_file(py_file):
            modified_count += 1
    print(f"\n{'=' * 50}")
    print(f"Summary: Modified {modified_count} out of {len(python_files)} file(s)")


if __name__ == "__main__":
    print("Starting multiprocessing to concurrent.futures conversion...\n")
    find_and_replace_in_directory()
    print("\nConversion complete!")
