from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from fnmatch import fnmatch
import argparse
import sys


def get_tree_structure(root_path, max_depth=None, include_pattern=None, exclude_pattern=None, current_depth=0):
    root = Path(root_path).resolve()

    if not root.exists():
        return None

    if max_depth is not None and current_depth > max_depth:
        return None

    try:
        entries = sorted(root.iterdir(), key=lambda x: (not x.is_dir(), x.name))
    except PermissionError:
        return None

    filtered_entries = []
    for entry in entries:
        if include_pattern and not fnmatch(entry.name, include_pattern):
            continue
        if exclude_pattern and fnmatch(entry.name, exclude_pattern):
            continue
        filtered_entries.append(entry)

    return {"path": root, "is_dir": True, "children": filtered_entries, "depth": current_depth}


def build_tree_parallel(node, max_depth=None, include_pattern=None, exclude_pattern=None):
    if node is None or (max_depth is not None and node["depth"] >= max_depth):
        return node

    children = node["children"]
    node["children"] = []

    def process_child(child):
        if child.is_dir():
            subtree = get_tree_structure(child, max_depth, include_pattern, exclude_pattern, node["depth"] + 1)
            if subtree:
                return build_tree_parallel(subtree, max_depth, include_pattern, exclude_pattern)
        return {"path": child, "is_dir": child.is_dir(), "children": [], "depth": node["depth"] + 1}

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(process_child, child): child for child in children}
        for future in as_completed(futures):
            result = future.result()
            if result:
                node["children"].append(result)

    node["children"].sort(key=lambda x: (not x["is_dir"], x["path"].name))
    return node


def print_tree(node, prefix="", is_last=True, show_counts=True):
    if node is None:
        return 0, 0

    connector = "└── " if is_last else "├── "
    extension = "    " if is_last else "│   "

    if node["depth"] > 0:
        print(f"{prefix}{connector}{node['path'].name}")
    else:
        print(f"{node['path'].name}/")

    dirs = 0
    files = 0
    children = node.get("children", [])

    for i, child in enumerate(children):
        is_last_child = i == len(children) - 1
        child_prefix = prefix + extension if node["depth"] > 0 else ""
        child_dirs, child_files = print_tree(child, child_prefix, is_last_child, show_counts=False)

        if child["is_dir"]:
            dirs += 1 + child_dirs
        else:
            files += 1
        files += child_files

    if node["depth"] == 0 and show_counts and (dirs > 0 or files > 0):
        print(f"\n{dirs} directories, {files} files")

    return dirs, files


def main():
    parser = argparse.ArgumentParser(description="Tree command implementation")
    parser.add_argument("path", nargs="?", default=".", help="Root path (default: current directory)")
    parser.add_argument("-L", "--max-depth", type=int, help="Maximum depth to display")
    parser.add_argument("-P", "--pattern", help="Include files matching pattern")
    parser.add_argument("-I", "--ignore-pattern", help="Exclude files matching pattern")
    parser.add_argument("--no-count", action="store_true", help="Don't show file/dir counts")

    args = parser.parse_args()

    root_path = Path(args.path)
    if not root_path.exists():
        print(f"Error: {args.path} does not exist", file=sys.stderr)
        return 1

    tree = get_tree_structure(
        root_path, max_depth=args.max_depth, include_pattern=args.pattern, exclude_pattern=args.ignore_pattern
    )

    if tree:
        tree = build_tree_parallel(tree, args.max_depth, args.pattern, args.ignore_pattern)
        print_tree(tree, show_counts=not args.no_count)

    return 0


if __name__ == "__main__":
    sys.exit(main())
