from __future__ import annotations

import argparse
import ast
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


class ParentMapper(ast.NodeVisitor):
    def __init__(self):
        self.parents = {}

    def visit(self, node):
        for child in ast.iter_child_nodes(node):
            self.parents[child] = node
        self.generic_visit(node)


def get_ancestors(node: ast.AST, parent_map: dict) -> list[ast.AST]:
    ancestors = []
    current = node
    while current in parent_map:
        current = parent_map[current]
        ancestors.append(current)
    return ancestors


def is_in_restricted_scope(node: ast.AST, parent_map: dict) -> bool:
    ancestors = get_ancestors(node, parent_map)
    restricted_types = (
        ast.Try,
        ast.If,
        ast.With,
        ast.AsyncWith,
        ast.ClassDef,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.Lambda,
        ast.For,
        ast.AsyncFor,
        ast.While,
    )
    return any(isinstance(ancestor, restricted_types) for ancestor in ancestors)


def find_imports_not_at_head(file_path: Path) -> list[tuple[int, int, str]]:
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"  [SKIP] {file_path}: Could not parse ({e})")
        return []
    mapper = ParentMapper()
    mapper.visit(tree)
    parent_map = mapper.parents
    head_end_line = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            head_end_line = max(head_end_line, node.end_lineno or node.lineno)
        elif isinstance(node, ast.Expr):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                head_end_line = max(head_end_line, node.end_lineno or node.lineno)
            else:
                break
        else:
            break
    misplaced_imports = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if node.lineno <= head_end_line:
                continue
            if is_in_restricted_scope(node, parent_map):
                continue
            lines = source.split("\n")
            import_text = "\n".join(lines[node.lineno - 1 : node.end_lineno])
            misplaced_imports.append((node.lineno, node.end_lineno or node.lineno, import_text))
    return misplaced_imports


def autofix_imports(file_path: Path, misplaced_imports: list[tuple[int, int, str]]) -> bool:
    if not misplaced_imports:
        return False
    source = file_path.read_text(encoding="utf-8")
    lines = source.split("\n")
    imports_to_move = []
    for line_num, end_line, import_text in misplaced_imports:
        imports_to_move.append(import_text)
    for line_num, end_line, _ in sorted(misplaced_imports, reverse=True):
        del lines[line_num - 1 : end_line]
    insert_index = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            insert_index = i + 1
        elif stripped.startswith(('"""', "'''")):
            if stripped.count('"""') == 2 or stripped.count("'''") == 2:
                insert_index = i + 1
            else:
                quote_char = '"""' if '"""' in stripped else "'''"
                for j in range(i + 1, len(lines)):
                    if quote_char in lines[j]:
                        insert_index = j + 1
                        break
                break
        elif stripped.startswith(("import ", "from ")):
            insert_index = i + 1
        else:
            break
    new_lines = lines[:insert_index] + imports_to_move + [""] + lines[insert_index:]
    file_path.write_text("\n".join(new_lines), encoding="utf-8")
    return True


def process_file(file_path: Path, autofix: bool) -> tuple[bool, bool, list[str]]:
    misplaced = find_imports_not_at_head(file_path)
    if not misplaced:
        return False, False, []
    details = []
    for line_num, _end_line, import_text in misplaced:
        detail = f"  Line {line_num}: {import_text.strip()}"
        print(detail)
        details.append(detail)
    if autofix:
        if autofix_imports(file_path, misplaced):
            msg = f"  [FIXED] Moved {len(misplaced)} import(s) to top"
            print(msg)
            details.append(msg)
            return True, True, details
        else:
            msg = "  [ERROR] Failed to fix"
            print(msg)
            details.append(msg)
            return True, False, details
    return True, False, details


def save_report(report_data: list[tuple[Path, list[str]]], output_file: str, autofix: bool):
    with open(output_file, "w", encoding="utf-8") as f:
        if not report_data:
            f.write("No misplaced imports found! All files are clean.\n")
            return
        for file_path, details in report_data:
            f.write(f"File: {file_path}\n")
            f.write(f"{'-' * 40}\n")
            f.writelines(f"{detail}\n" for detail in details)
            f.write("\n")
        if autofix:
            fixed = sum(1 for _, details in report_data if any("[FIXED]" in d for d in details))
            f.write(f"  Files fixed: {fixed}\n")
            f.write(f"  Files with errors: {len(report_data) - fixed}\n")


def main():
    parser = argparse.ArgumentParser(description="Find .py files with imports not at the head of the file")
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan (default: current directory)",
    )
    parser.add_argument(
        "-a",
        "--autofix",
        action="store_true",
        help="Automatically move misplaced imports to the top of the file",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Save report to file",
    )
    parser.add_argument("-j", "--jobs", type=int, default=8, help="Number of parallel jobs (default: 4)")
    args = parser.parse_args()
    output_file = args.output or (None if args.autofix else "errors.txt")
    root = Path(args.directory)
    if not root.exists():
        print(f"Error: Directory '{root}' does not exist")
        sys.exit(1)
    if root.is_file():
        files = [root] if root.suffix == ".py" else []
    else:
        files = sorted(root.rglob("*.py"))
    if not files:
        print(f"No .py files found in '{root}'")
        return
    print(f"Scanning {len(files)} Python file(s) with {args.jobs} worker(s)...")
    files_with_issues = 0
    files_fixed = 0
    report_data = []
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {executor.submit(process_file, fp, args.autofix): fp for fp in files}
        for future in as_completed(futures):
            has_issues, was_fixed, details = future.result()
            if has_issues:
                files_with_issues += 1
                report_data.append((futures[future], details))
            if was_fixed:
                files_fixed += 1
    print(f"\n{'=' * 40}")
    print("Summary:")
    print(f"  Files with misplaced imports: {files_with_issues}")
    if args.autofix:
        print(f"  Files fixed: {files_fixed}")
    else:
        print("  Run with -a to autofix")
    if output_file and (files_with_issues > 0 or args.output):
        save_report(report_data, output_file, args.autofix)
        print(f"  Report saved to: {output_file}")
    if files_with_issues > 0 and not args.autofix:
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
