from __future__ import annotations

import argparse
import ast
import hashlib
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


def normalize_function_source(node: ast.FunctionDef) -> str:
    func_copy = ast.FunctionDef(
        name=node.name,
        args=node.args,
        body=[
            n
            for n in node.body
            if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))
        ],
        decorator_list=node.decorator_list,
        returns=node.returns,
        type_comment=None,
        lineno=node.lineno,
        col_offset=node.col_offset,
    )
    source = ast.unparse(func_copy)
    lines = [l.strip() for l in source.split("\n") if l.strip()]
    return "\n".join(lines)


def hash_function_body(node: ast.FunctionDef) -> str:
    normalized = normalize_function_source(node)
    return hashlib.sha256(normalized.encode()).hexdigest()


def extract_functions(filepath: Path) -> dict[str, tuple[str, ast.FunctionDef, str]]:
    try:
        tree = ast.parse(filepath.read_text())
    except (SyntaxError, UnicodeDecodeError):
        return {}
    functions = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            func_hash = hash_function_body(node)
            normalized = normalize_function_source(node)
            functions[node.name] = (func_hash, node, normalized)
    return functions


def load_dh_functions(dh_path: Path) -> dict[str, tuple[str, str]]:
    dh_functions = {}
    py_files = sorted(dh_path.glob("**/*.py"))
    for pyfile in py_files:
        funcs = extract_functions(pyfile)
        for fname, (fhash, _, normalized) in funcs.items():
            if fname in dh_functions:
                print(f"Warning: duplicate function '{fname}' in dh package")
            dh_functions[fname] = (fhash, normalized)
    return dh_functions


def get_function_source_lines(filepath: Path, func_name: str) -> int:
    tree = ast.parse(filepath.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return node.lineno, node.end_lineno
    return None, None


def transform_file(
    filepath: Path,
    dh_functions: dict[str, tuple[str, str]],
    apply: bool,
    debug: bool = False,
) -> tuple[Path, bool, str]:
    try:
        content = filepath.read_text()
        tree = ast.parse(content)
    except (SyntaxError, UnicodeDecodeError):
        return filepath, False, ""
    file_functions = extract_functions(filepath)
    to_import = set()
    debug_info = []
    for fname, (file_hash, node, _file_normalized) in file_functions.items():
        if fname in dh_functions:
            dh_hash, _dh_normalized = dh_functions[fname]
            if file_hash == dh_hash:
                to_import.add(fname)
                if debug:
                    debug_info.append(f"  ✓ {fname}: hash match")
            else:
                if debug:
                    debug_info.append(f"  ✗ {fname}: hash mismatch")
                    if False:
                        print(f"    File hash: {file_hash}")
                        print(f"    Dh hash:   {dh_hash}")
        else:
            if debug:
                debug_info.append(f"  ? {fname}: not in dh package")
    if debug and debug_info:
        print(f"{filepath.name}:")
        for info in debug_info:
            print(info)
    if not to_import:
        return filepath, False, ""
    new_body = []
    import_added = False
    skip_next_funcs = to_import
    for node in tree.body:
        is_removable_func = isinstance(node, ast.FunctionDef) and node.name in skip_next_funcs
        if is_removable_func:
            if not import_added:
                import_line = f"from dh import {', '.join(sorted(to_import))}\n"
                new_body.append(import_line)
                import_added = True
            continue
        elif isinstance(node, ast.ImportFrom) and node.module == "dh":
            if not import_added:
                existing_names = {alias.name for alias in node.names}
                combined = existing_names | to_import
                import_line = f"from dh import {', '.join(sorted(combined))}\n"
                new_body.append(import_line)
                import_added = True
            continue
        else:
            new_body.append(ast.unparse(node))
    new_content = "\n".join(new_body)
    if apply:
        filepath.write_text(new_content)
        return filepath, True, f"Updated {filepath.name}: removed {sorted(to_import)}"
    else:
        return (
            filepath,
            False,
            f"Would update {filepath.name}: remove {sorted(to_import)}",
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=[Path.cwd()],
        help="Files or directories to process (default: current directory)",
    )
    parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="Apply changes in-place (default: dry-run)",
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Show function matching details",
    )
    args = parser.parse_args()
    dh_path = Path.home() / "projects" / "py" / "dh" / "src" / "dh"
    if not dh_path.exists():
        print(f"Error: dh package not found at {dh_path}")
        return 1
    print(f"Loading dh functions from {dh_path}...")
    dh_functions = load_dh_functions(dh_path)
    print(f"Loaded {len(dh_functions)} functions from dh package\n")
    target_files = []
    for path in args.paths:
        if path.is_file():
            target_files.append(path)
        elif path.is_dir():
            target_files.extend(path.glob("**/*.py"))
    target_files = [f for f in target_files if f.name != "dh_reverse.py"]
    if not target_files:
        print("No Python files found to process.")
        return 0
    print(f"Processing {len(target_files)} Python files...\n")
    mode = "DRY RUN" if not args.apply else "APPLYING CHANGES"
    print(f"Mode: {mode}\n")
    updated_count = 0
    with ProcessPoolExecutor() as executor:
        futures = {executor.submit(transform_file, f, dh_functions, args.apply, args.debug): f for f in target_files}
        for future in as_completed(futures):
            _filepath, updated, message = future.result()
            if message:
                print(message)
            if updated:
                updated_count += 1
    print(f"\n{'=' * 40}")
    if args.apply:
        print(f"Updated {updated_count} files")
    else:
        print(f"Would update {updated_count} files (use -a/--apply to apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
