from __future__ import annotations

import argparse
import multiprocessing
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


def has_main_guard(content):
    pattern = r"if\s+__name__\s*==\s*[\"\']__main__[\"\']\s*:"
    return bool(re.search(pattern, content))


def add_main_function(content):
    if "def main()" in content:
        return content
    lines = content.split("\n")
    insert_pos = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            insert_pos = i + 1
        elif stripped and insert_pos == 0:
            insert_pos = 0
    main_func = '\n\ndef main():\n    # TODO: Add your main logic here\n    print("Hello from main!")\n'
    lines.insert(insert_pos, main_func)
    return "\n".join(lines)


def add_main_guard(content):
    if has_main_guard(content):
        return content
    content = content.rstrip()
    guard_code = '\nif __name__ == "__main__":\n    raise SystemExit(main())\n'
    return content + guard_code


def process_file(filepath, add=False, dry_run=False):
    try:
        path = Path(filepath)
        content = path.read_text(encoding="utf-8")
        if has_main_guard(content):
            return ("skipped", "Already has guard", path)
        if not add:
            return ("missing", "Missing guard", path)
        new_content = add_main_function(content)
        new_content = add_main_guard(new_content)
        if dry_run:
            return ("would_add", "Would add guard", path)
        path.write_text(new_content, encoding="utf-8")
        return ("added", "Added guard successfully", path)
    except Exception as e:
        return ("error", str(e), Path(filepath))


def find_python_files(directory, exclude_patterns=None):
    if exclude_patterns is None:
        exclude_patterns = [
            ".git",
            "__pycache__",
            "venv",
            ".venv",
            "env",
            "dist",
            "build",
            ".pytest_cache",
            ".mypy_cache",
        ]
    root = Path(directory)
    exclude_glob = []
    for pattern in exclude_patterns:
        exclude_glob.extend([f"**/{pattern}", f"**/{pattern}/*"])
    py_files = list(root.rglob("*.py"))
    filtered = []
    for f in py_files:
        should_exclude = False
        for pattern in exclude_patterns:
            if pattern in f.parts:
                should_exclude = True
                break
        if not should_exclude:
            filtered.append(f)
    return filtered


def main():
    parser = argparse.ArgumentParser(
        description="Find and optionally add main guard to Python files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\nExamples:\n  %(prog)s                    # Find missing guards in current directory\n  %(prog)s -a                 # Add guards to all missing files\n  %(prog)s src/ -a            # Check src/ directory and add guards\n  %(prog)s -a --dry-run       # Preview changes without modifying\n  %(prog)s -j 4 -a            # Use 4 parallel processes\n        ",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan (default: current directory)",
    )
    parser.add_argument("-a", "--add", action="store_true", help="Add the main guard to missing files")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without actually modifying files",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=None,
        help="Number of parallel processes (default: CPU count)",
    )
    parser.add_argument("--exclude", nargs="+", default=[], help="Additional directories to exclude")
    args = parser.parse_args()
    exclude_patterns = [
        ".git",
        "__pycache__",
        "venv",
        ".venv",
        "env",
        "dist",
        "build",
        ".pytest_cache",
        ".mypy_cache",
    ]
    exclude_patterns.extend(args.exclude)
    max_workers = args.jobs or multiprocessing.cpu_count()
    print(f"📂 Scanning: {args.directory}")
    print(f"🚫 Excluding: {', '.join(exclude_patterns)}")
    print(f"⚡ Using {max_workers} parallel workers")
    py_files = find_python_files(args.directory, exclude_patterns)
    total = len(py_files)
    if total == 0:
        print("\n⚠️  No Python files found!")
        return
    print(f"\n📄 Found {total} Python files")
    results = {
        "has_guard": [],
        "missing": [],
        "added": [],
        "would_add": [],
        "skipped": [],
        "errors": [],
    }
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_file, f, args.add, args.dry_run): f for f in py_files}
        completed = 0
        for future in as_completed(futures):
            status, message, filepath = future.result()
            completed += 1
            if completed % 10 == 0 or completed == total:
                print(f"\r⏳ Processing: {completed}/{total}", end="", flush=True)
            if status == "missing":
                results["missing"].append(filepath)
            elif status == "added":
                results["added"].append(filepath)
            elif status == "would_add":
                results["would_add"].append(filepath)
            elif status == "skipped":
                results["skipped"].append(filepath)
            elif status == "error":
                results["errors"].append((filepath, message))
    print()
    has_guard = len(results["skipped"])
    missing = len(results["missing"])
    if args.add:
        added = len(results["added"])
        would_add = len(results["would_add"])
        errors = len(results["errors"])
        print("\n📊 Results:")
        print(f"  ✅ Already had guard: {has_guard}")
        if args.dry_run:
            print(f"  🔍 Would add guard: {would_add}")
        else:
            print(f"  ➕ Added guard: {added}")
        print(f"  ❌ Errors: {errors}")
        if errors > 0:
            print("\n❌ Errors encountered:")
            for path, error in results["errors"]:
                print(f"  {path}: {error}")
        if args.dry_run and would_add > 0:
            print(f"\n🔍 Dry run complete: Would have modified {would_add} files")
            print("   Run without --dry-run to apply changes")
    else:
        print(f"\n📋 Found {missing} files without the main guard:")
        for path in sorted(results["missing"]):
            rel_path = path.relative_to(args.directory) if args.directory != "." else path
            print(f"  {rel_path}")
        if missing > 0:
            print(f"\n💡 Run with -a to add the guard: python {sys.argv[0]} {args.directory} -a")
        else:
            print("\n✅ All Python files have the main guard!")
    if args.add and (not args.dry_run) and results["added"]:
        print(f"\n✅ Successfully added main guard to {len(results['added'])} files")


if __name__ == "__main__":
    raise SystemExit(main())
