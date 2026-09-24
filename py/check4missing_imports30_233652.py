import ast
import sys
from pathlib import Path
from multiprocessing import Pool, cpu_count
from typing import List, Tuple, Set
import argparse


def get_python_files(root_dir: Path) -> List[Path]:
    return list(root_dir.rglob("*.py"))


def extract_imports(file_path: Path) -> Set[str]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError):
        return set()

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])

    return imports


def extract_used_names(file_path: Path) -> Set[str]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError):
        return set()

    names = set()
    builtins = set(dir(__builtins__))

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name):
                names.add(node.value.id)

    return names - builtins - {"self", "cls"}


def check_file(file_path: Path) -> Tuple[Path, List[str]]:
    imported = extract_imports(file_path)
    used = extract_used_names(file_path)

    missing = []

    for name in used:
        if name not in imported and not name[0].isupper():
            try:
                __import__(name)
                missing.append(name)
            except ImportError:
                pass

    return file_path, missing


def fix_file(file_path: Path, missing_imports: List[str]) -> None:
    if not missing_imports:
        return

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return

    insert_pos = 0
    for i, node in enumerate(tree.body):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            insert_pos = i + 1
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            insert_pos = i + 1
        else:
            break

    lines = content.split("\n")
    import_lines = [f"import {name}" for name in sorted(set(missing_imports))]
    import_text = "\n".join(import_lines) + "\n"

    line_count = 0
    for node in tree.body[:insert_pos]:
        line_count = node.end_lineno or line_count

    lines.insert(line_count, import_text)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description="Check Python files for missing imports recursively.")
    parser.add_argument(
        "-a",
        "--auto-fix",
        action="store_true",
        help="Automatically add missing imports to files",
    )
    parser.add_argument(
        "-d",
        "--directory",
        type=Path,
        default=Path.cwd(),
        help="Root directory to scan (default: current directory)",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=cpu_count(),
        help=f"Number of parallel jobs (default: {cpu_count()})",
    )

    args = parser.parse_args()

    root_dir = args.directory
    if not root_dir.is_dir():
        print(f"Error: {root_dir} is not a valid directory")
        sys.exit(1)

    print(f"Scanning {root_dir} for Python files...")
    python_files = get_python_files(root_dir)

    if not python_files:
        print("No Python files found.")
        sys.exit(0)

    print(f"Found {len(python_files)} Python file(s). Checking with {args.jobs} workers...")

    files_with_issues = []
    with Pool(processes=args.jobs) as pool:
        results = pool.map(check_file, python_files)

    for file_path, missing in results:
        if missing:
            files_with_issues.append((file_path, missing))
            rel_path = file_path.relative_to(root_dir)
            print(f"\n{rel_path}:")
            for imp in sorted(set(missing)):
                print(f"  - Missing: {imp}")

            if args.auto_fix:
                fix_file(file_path, missing)
                print(f"  ✓ Fixed")

    print(f"\n{'=' * 60}")
    if files_with_issues:
        print(f"Files with missing imports: {len(files_with_issues)}")
        if args.auto_fix:
            print("Files have been automatically fixed.")
    else:
        print("No missing imports detected!")


if __name__ == "__main__":
    main()
