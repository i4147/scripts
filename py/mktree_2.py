from __future__ import annotations

import re
import sys
from pathlib import Path


def parse_tree_file(filename):
    paths = []
    try:
        with open(filename, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: File '{filename}' not found.")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading file: {e}")
        sys.exit(1)
    path_stack = []
    prev_depth = -1
    for line in lines:
        if not line.strip():
            continue
        depth = 0
        for char in line:
            if char in ("│", " ", "\t"):
                depth += 1
            else:
                break
        indentation = len(line) - len(line.lstrip(" │├└─"))
        depth = indentation // 4 if indentation > 0 else 0
        clean_line = line.strip()
        clean_line = re.sub(r"^[├└─]+\s*", "", clean_line)
        clean_line = re.sub(r"^│\s*", "", clean_line)
        if not clean_line or clean_line in ("├──", "└──", "│"):
            continue
        is_directory = clean_line.endswith("/")
        name = clean_line.rstrip("/")
        if depth == 0 and is_directory:
            continue
        while len(path_stack) > depth:
            path_stack.pop()
        if path_stack:
            parent_path = path_stack[-1] if len(path_stack) > depth else Path(*path_stack[:depth])
        else:
            parent_path = Path(".")
        current_path = parent_path / name
        paths.append((current_path, is_directory))
        if is_directory:
            if len(path_stack) <= depth:
                path_stack.append(current_path)
            else:
                path_stack[depth] = current_path
    return paths


def create_tree(paths):
    created_dirs = 0
    created_files = 0
    for path, is_directory in paths:
        try:
            if is_directory:
                path.mkdir(parents=True, exist_ok=True)
                print(f"Created directory: {path}")
                created_dirs += 1
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch(exist_ok=True)
                print(f"Created file: {path}")
                created_files += 1
        except Exception as e:
            print(f"Error creating {path}: {e}")
    return created_dirs, created_files


def main():
    input_file = sys.argv[1] if len(sys.argv) > 1 else "tree.txt"
    print(f"Reading tree structure from: {input_file}")
    print("-" * 50)
    paths = parse_tree_file(input_file)
    if not paths:
        print("No valid paths found in the tree file.")
        sys.exit(1)
    created_dirs, created_files = create_tree(paths)
    print("-" * 50)
    print("Summary:")
    print(f"  Directories created: {created_dirs}")
    print(f"  Files created: {created_files}")
    print(f"  Total items: {created_dirs + created_files}")


if __name__ == "__main__":
    raise SystemExit(main())
