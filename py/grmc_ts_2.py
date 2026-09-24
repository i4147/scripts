import argparse
import ast
import sys
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final
import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Tree, TreeCursor

MAX_WORKERS = 8
PRESERVE_PREFIXES = ("#!", "# type:", "# fmt:")
PRESERVE_EXACT = frozenset({"# fmt: skip", "# fmt: on", "# fmt: off"})
PY_LANGUAGE = Language(tspython.language())
Removal = tuple[int, int, bytes]


def get_parser():
    return Parser(PY_LANGUAGE)


def should_preserve_comment(comment_bytes):
    text = comment_bytes.decode("utf-8", errors="ignore").strip()
    return text.startswith(PRESERVE_PREFIXES) or text in PRESERVE_EXACT


def process_file(file_path):
    try:
        source_bytes = file_path.read_bytes()
    except Exception as exc:
        return f"[ERROR] Failed to read {file_path}: {exc}"
    parser = get_parser()
    tree = parser.parse(source_bytes)
    root = tree.root_node
    removals = []
    module_docstring_node = None
    if root.child_count > 0:
        first_child = root.child(0)
        if first_child is not None and first_child.type == "expression_statement":
            expr_child = first_child.child(0)
            if expr_child is not None and expr_child.type == "string":
                module_docstring_node = first_child
    cursor = tree.walk()
    reached_end = False
    while not reached_end:
        node = cursor.node
        if node.type == "comment":
            node_bytes = source_bytes[node.start_byte : node.end_byte]
            if not should_preserve_comment(node_bytes):
                removals.append((node.start_byte, node.end_byte, b""))
        elif node.type == "expression_statement" and node != module_docstring_node:
            expr_child = node.child(0)
            if expr_child is not None and expr_child.type == "string":
                parent = node.parent
                if parent is not None and parent.type == "block":
                    if parent.named_child_count == 1:
                        removals.append((node.start_byte, node.end_byte, b"pass"))
                    else:
                        removals.append((node.start_byte, node.end_byte, b""))
        if cursor.goto_first_child():
            continue
        if cursor.goto_next_sibling():
            continue
        while True:
            if not cursor.goto_parent():
                reached_end = True
                break
            if cursor.goto_next_sibling():
                break
    if not removals:
        return f"[SKIPPED] No structural modifications needed for {file_path}"
    removals.sort(key=lambda item: item[0], reverse=True)
    modified_bytes = bytearray(source_bytes)
    for start, end, replacement in removals:
        modified_bytes[start:end] = replacement
    final_code = bytes(modified_bytes)
    try:
        ast.parse(final_code, filename=str(file_path))
    except SyntaxError as exc:
        return f"[WARNING] Validation failed for {file_path} (Changes rejected): {exc}"
    try:
        file_path.write_bytes(final_code)
        return f"[SUCCESS] Processed and stripped: {file_path}"
    except Exception as exc:
        return f"[ERROR] Failed to save updates to {file_path}: {exc}"


def gather_files(inputs):
    files = set()
    if not inputs:
        files.update(Path(".").rglob("*.py"))
        return sorted(files)
    for item in inputs:
        p = Path(item)
        if p.is_file() and p.suffix == ".py":
            files.add(p)
        elif p.is_dir():
            files.update(p.rglob("*.py"))
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(description="Strip comments and docstrings using Tree-Sitter safely.")
    parser.add_argument(
        "paths",
        nargs="*",
        help="Target files or directories to process. Defaults to '.' if empty.",
    )
    args = parser.parse_args()
    targets = gather_files(args.paths)
    if not targets:
        print("No target Python source files detected.")
        sys.exit(0)
    print(f"Queue loaded. Processing {len(targets)} target files via Parallel Pipeline...")
    with Pool(processes=MAX_WORKERS) as pool:
        async_results = [pool.apply_async(process_file, (target,)) for target in targets]
        for async_res in async_results:
            result_string = async_res.get()
            print(result_string)


if __name__ == "__main__":
    raise SystemExit(main())
