import argparse
import ast
import hashlib
import sys
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Final
from loguru import logger

DH_PACKAGE_PATH = Path.home() / "projects" / "py" / "dh" / "src" / "dh"
POOL_WORKERS = 8
EXCLUDED_FILENAMES = frozenset({"dh_reverse.py"})


def normalize_function_source(node):
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
    lines = [line.strip() for line in source.split("\n") if line.strip()]
    return "\n".join(lines)


def hash_function_body(node):
    normalized = normalize_function_source(node)
    return hashlib.sha256(normalized.encode()).hexdigest()


def extract_functions(
    path,
):
    try:
        tree = ast.parse(path.read_text())
    except (SyntaxError, UnicodeDecodeError):
        return {}
    functions = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            func_hash = hash_function_body(node)
            normalized = normalize_function_source(node)
            functions[node.name] = (func_hash, node, normalized)
    return functions


def load_dh_functions(dh_path):
    dh_functions = {}
    py_files = sorted(dh_path.glob("**/*.py"))
    for pyfile in py_files:
        funcs = extract_functions(pyfile)
        for fname, (fhash, _, normalized) in funcs.items():
            if fname in dh_functions:
                logger.warning(f"Duplicate function '{fname}' in dh package")
            dh_functions[fname] = (fhash, normalized)
    return dh_functions


def transform_file(
    path,
    dh_functions,
    apply,
    debug=False,
):
    try:
        content = path.read_text()
        tree = ast.parse(content)
    except (SyntaxError, UnicodeDecodeError):
        return path, False, ""
    file_functions = extract_functions(path)
    to_import = set()
    debug_info = []
    for fname, (file_hash, _node, _file_normalized) in file_functions.items():
        if fname in dh_functions:
            dh_hash, _dh_normalized = dh_functions[fname]
            if file_hash == dh_hash:
                to_import.add(fname)
                if debug:
                    debug_info.append(f"  ✓ {fname}: hash match")
            else:
                if debug:
                    debug_info.append(f"  ✗ {fname}: hash mismatch")
        else:
            if debug:
                debug_info.append(f"  ? {fname}: not in dh package")
    if debug and debug_info:
        logger.debug(f"{path.name}:")
        for info in debug_info:
            logger.debug(info)
    if not to_import:
        return path, False, ""
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
        path.write_text(new_content)
        return path, True, f"Updated {path.name}: removed {sorted(to_import)}"
    else:
        return (
            path,
            False,
            f"Would update {path.name}: remove {sorted(to_import)}",
        )


def parse_args(argv=None):
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
    return parser.parse_args(argv)


def collect_target_files(paths):
    target_files = []
    for path in paths:
        if path.is_file():
            target_files.append(path)
        elif path.is_dir():
            target_files.extend(path.glob("**/*.py"))
    return [f for f in target_files if f.name not in EXCLUDED_FILENAMES]


def _transform_worker(
    args,
):
    path, dh_functions, apply, debug = args
    return transform_file(path, dh_functions, apply, debug)


def main(argv=None):
    args = parse_args(argv)
    dh_path = DH_PACKAGE_PATH
    if not dh_path.exists():
        logger.error(f"dh package not found at {dh_path}")
        return 1
    print(f"Loading dh functions from {dh_path}...")
    dh_functions = load_dh_functions(dh_path)
    print(f"Loaded {len(dh_functions)} functions from dh package\n")
    target_files = collect_target_files(args.paths)
    if not target_files:
        print("No Python files found to process.")
        return 0
    print(f"Processing {len(target_files)} Python files...\n")
    mode = "DRY RUN" if not args.apply else "APPLYING CHANGES"
    print(f"Mode: {mode}\n")
    updated_count = 0
    work_items = [(f, dh_functions, args.apply, args.debug) for f in target_files]
    with Pool(processes=POOL_WORKERS) as pool:
        async_results = [pool.apply_async(_transform_worker, (item,)) for item in work_items]
        pool.close()
        pool.join()
    for result in async_results:
        _path, updated, message = result.get()
        if message:
            print(message)
        if updated:
            updated_count += 1
    print("=" * 40)
    if args.apply:
        print(f"Updated {updated_count} files")
    else:
        print(f"Would update {updated_count} files (use -a/--apply to apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
