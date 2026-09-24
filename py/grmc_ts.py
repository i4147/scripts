from __future__ import annotations

import argparse
import ast
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Parser

PY_LANGUAGE = Language(tspython.language())


def get_parser() -> Parser:
    parser = Parser(PY_LANGUAGE)
    return parser


def should_preserve_comment(comment_bytes: bytes) -> bool:
    text = comment_bytes.decode("utf-8", errors="ignore").strip()
    return (
        text.startswith(("#!", "# type:", "# fmt:"))
        or text == "# fmt: skip"
        or text == "# fmt: on"
        or text == "# fmt: off"
    )


def process_file(path: Path) -> str:
    try:
        source_bytes = path.read_bytes()
    except Exception as e:
        return f"[ERROR] Failed to read {path}: {e}"
    parser = get_parser()
    tree = parser.parse(source_bytes)
    root = tree.root_node
    removals = []
    module_docstring_node = None
    if root.child_count > 0:
        first_child = root.child(0)
        if first_child.type == "expression_statement":
            expr_child = first_child.child(0)
            if expr_child and expr_child.type == "string":
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
            if expr_child and expr_child.type == "string":
                parent = node.parent
                if parent and parent.type == "block":
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
        return f"[SKIPPED] No structural modifications needed for {path}"
    removals.sort(key=lambda x: x[0], reverse=True)
    modified_bytes = bytearray(source_bytes)
    for start, end, replacement in removals:
        modified_bytes[start:end] = replacement
    final_code = bytes(modified_bytes)
    try:
        ast.parse(final_code, filename=str(path))
    except SyntaxError as e:
        return f"[WARNING] Validation failed for {path} (Changes rejected): {e}"
    try:
        path.write_bytes(final_code)
        return f"[SUCCESS] Processed and stripped: {path}"
    except Exception as e:
        return f"[ERROR] Failed to save updates to {path}: {e}"


def gather_files(inputs) -> list[Path]:
    files = []
    if not inputs:
        return list(Path(".").rglob("*.py"))
    for item in inputs:
        p = Path(item)
        if p.is_file() and p.suffix == ".py":
            files.append(p)
        elif p.is_dir():
            files.extend(p.rglob("*.py"))
    return files


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
    with ProcessPoolExecutor() as executor:
        futures = {executor.submit(process_file, target): target for target in targets}
        for future in as_completed(futures):
            result_string = future.result()
            print(result_string)


if __name__ == "__main__":
    raise SystemExit(main())
