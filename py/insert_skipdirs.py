from __future__ import annotations

import ast
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

INSERT_TEXT = "\n\n"


def get_module_level_imports(tree: ast.AST) -> int:
    last_import_line = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if node.end_lineno and node.end_lineno > last_import_line:
                last_import_line = node.end_lineno
        elif not isinstance(node, ast.Expr):
            break
    return last_import_line


def find_import_section_end(content: str) -> int | None:
    try:
        tree = ast.parse(content)
        last_import_line = get_module_level_imports(tree)
        if last_import_line > 0:
            lines = content.splitlines(True)
            if last_import_line <= len(lines):
                pos = sum(len(line) for line in lines[:last_import_line])
                return pos
    except SyntaxError:
        pass
    return None


def validate_modified_code(original: str, modified: str) -> bool:
    try:
        ast.parse(modified)
        return True
    except SyntaxError as e:
        print(f"  Validation failed: {e}")
        return False


def process_file(file_path: Path) -> tuple[Path, bool, str]:
    try:
        content = file_path.read_text(encoding="utf-8")
        if "SKIP_DIRS" in content:
            return (file_path, False, "already_has_skip_dirs")
        try:
            ast.parse(content)
        except SyntaxError as e:
            return (file_path, False, f"syntax_error_original: {e}")
        insert_pos = find_import_section_end(content)
        if insert_pos is None:
            lines = content.splitlines(True)
            start_pos = 0
            line_idx = 0
            if lines and lines[0].startswith("#!"):
                start_pos += len(lines[0])
                line_idx += 1
            if line_idx < len(lines) and "coding" in lines[line_idx]:
                start_pos += len(lines[line_idx])
                line_idx += 1
            remaining_content = content[start_pos:]
            remaining_stripped = remaining_content.lstrip()
            for quote in ('"""', "'''"):
                if remaining_stripped.startswith(quote):
                    idx = remaining_stripped.find(quote, len(quote))
                    if idx != -1:
                        offset = len(remaining_content) - len(remaining_stripped)
                        start_pos += offset + idx + len(quote)
                        break
            insert_pos = start_pos
        if insert_pos > 0:
            before_char = content[insert_pos - 1 : insert_pos]
            if before_char not in ("\n", "\r"):
                insert_text = "\n" + INSERT_TEXT
            else:
                insert_text = INSERT_TEXT
        else:
            insert_text = INSERT_TEXT
        modified_content = content[:insert_pos] + insert_text + content[insert_pos:]
        if not validate_modified_code(content, modified_content):
            return (file_path, False, "validation_failed")
        file_path.write_text(modified_content, encoding="utf-8")
        return (file_path, True, "success")
    except Exception as e:
        return (file_path, False, f"exception: {e!s}")


def find_python_files(root_dir: Path = Path(".")) -> list[Path]:
    python_files = []
    for py_file in root_dir.rglob("*.py"):
        parts = set(py_file.parent.parts)
        if parts & SKIP_DIRS:
            continue
        python_files.append(py_file)
    return sorted(python_files)


def main():
    root_dir = Path(".")
    print("Finding Python files...")
    python_files = find_python_files(root_dir)
    print(f"Found {len(python_files)} Python files\n")
    if not python_files:
        print("No Python files to process")
        return
    stats = {
        "modified": 0,
        "already_has": 0,
        "validation_failed": 0,
        "syntax_error": 0,
        "other_errors": 0,
    }
    print(f"Processing files using {min(len(python_files), 8)} workers...\n")
    with ProcessPoolExecutor(max_workers=min(len(python_files), 8)) as executor:
        future_to_file = {executor.submit(process_file, file_path): file_path for file_path in python_files}
        for future in as_completed(future_to_file):
            file_path = future_to_file[future]
            try:
                path, was_modified, status = future.result()
                if was_modified:
                    stats["modified"] += 1
                    print(f"✓ Modified: {path}")
                elif status == "already_has_skip_dirs":
                    stats["already_has"] += 1
                elif status == "validation_failed":
                    stats["validation_failed"] += 1
                    print(f"✗ Validation failed: {path}")
                elif status.startswith("syntax_error"):
                    stats["syntax_error"] += 1
                    print(f"✗ Syntax error: {path}")
                else:
                    stats["other_errors"] += 1
                    print(f"✗ {status}: {path}")
            except Exception as e:
                stats["other_errors"] += 1
                print(f"✗ Exception processing {file_path}: {e}")
    (
        stats["modified"]
        + stats["already_has"]
        + stats["validation_failed"]
        + stats["syntax_error"]
        + stats["other_errors"]
    )
    print(f"\n{'=' * 42}")
    print("Summary:")
    print(f"  Total files found:           {len(python_files)}")
    print(f"  Modified:                    {stats['modified']}")
    print(f"  Already has SKIP_DIRS:       {stats['already_has']}")
    print(f"  Validation failed:           {stats['validation_failed']}")
    print(f"  Syntax errors (original):    {stats['syntax_error']}")
    print(f"  Other errors:                {stats['other_errors']}")
    print(f"{'=' * 42}")
    if stats["modified"] > 0:
        print(f"\n✓ Successfully modified {stats['modified']} file(s)")
    if stats["validation_failed"] > 0 or stats["syntax_error"] > 0:
        print(f"\n⚠ Check {stats['validation_failed'] + stats['syntax_error']} file(s) with errors")


if __name__ == "__main__":
    main()
