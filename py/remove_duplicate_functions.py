from __future__ import annotations

import argparse
import ast
import hashlib
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def normalize_function_body(lines, start_idx, end_idx):
    body_lines = lines[start_idx:end_idx]
    if not body_lines:
        return ""
    stripped = [line for line in body_lines if line.strip()]
    if not stripped:
        return ""
    min_indent = min(len(line) - len(line.lstrip()) for line in stripped)
    return "\n".join(line[min_indent:] if line.strip() else "" for line in body_lines)


def compute_function_hash(filepath, func_node):
    try:
        lines = filepath.read_text().splitlines(keepends=True)
    except Exception:
        return None
    start_line = func_node.lineno - 1
    end_line = func_node.end_lineno
    func_lines = lines[start_line:end_line]
    body_start = 0
    for i, line in enumerate(func_lines):
        if ":" in line and not line.strip().startswith("@"):
            body_start = i + 1
            break
    sig = ast.dump(func_node.args)
    if func_node.returns:
        sig += ast.dump(func_node.returns)
    body = normalize_function_body(func_lines, body_start, len(func_lines))
    content = f"{sig}\n{body}"
    return hashlib.md5(content.encode()).hexdigest()


def extract_top_level_functions(filepath):
    try:
        tree = ast.parse(filepath.read_text(), filename=str(filepath))
    except SyntaxError:
        return None
    except Exception:
        return None
    functions = {}
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef):
            content_hash = compute_function_hash(filepath, node)
            if content_hash:
                functions[node.name] = {
                    "name": node.name,
                    "hash": content_hash,
                    "lineno": node.lineno,
                    "end_lineno": node.end_lineno,
                }
    return functions


def process_target_file(target_path, ref_hashes, apply=False):
    funcs = extract_top_level_functions(target_path)
    if funcs is None or not funcs:
        return {"file": target_path, "status": "skipped", "duplicates": []}
    duplicates = []
    for func_name, func_info in funcs.items():
        if func_info["hash"] in ref_hashes:
            duplicates.append(
                {
                    "name": func_name,
                    "lineno": func_info["lineno"],
                    "end_lineno": func_info["end_lineno"],
                    "ref_name": ref_hashes[func_info["hash"]],
                }
            )
    if not duplicates:
        return {"file": target_path, "status": "ok", "duplicates": []}
    if apply:
        try:
            lines = target_path.read_text().splitlines(keepends=True)
            duplicates.sort(key=lambda x: x["lineno"], reverse=True)
            removed = []
            for dup in duplicates:
                start = dup["lineno"] - 1
                end = dup["end_lineno"]
                while start > 0 and (lines[start - 1].strip().startswith("@") or lines[start - 1].strip() == ""):
                    start -= 1
                del lines[start:end]
                removed.append(dup["name"])
            target_path.write_text("".join(lines))
            return {"file": target_path, "status": "updated", "duplicates": removed}
        except Exception as e:
            return {
                "file": target_path,
                "status": "error",
                "error": str(e),
                "duplicates": [],
            }
    return {"file": target_path, "status": "found", "duplicates": duplicates}


def expand_input_paths(inputs):
    py_files = set()
    if not inputs:
        py_files.update(Path(".").rglob("*.py"))
    else:
        for item in inputs:
            path = Path(item)
            if path.is_file() and path.suffix == ".py":
                py_files.add(path)
            elif path.is_dir():
                py_files.update(path.rglob("*.py"))
    return sorted(py_files)


def main():
    parser = argparse.ArgumentParser(
        description="Remove duplicate functions from Python files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
        "  %(prog)s ref.py module.py\n"
        "  %(prog)s ref.py src/\n"
        "  %(prog)s ref.py  # scan current dir\n"
        "  %(prog)s -a ref.py target.py  # actually remove",
    )
    parser.add_argument("reference", help="Reference file (functions to keep)")
    parser.add_argument("inputs", nargs="*", help="Target files/directories (default: .)")
    parser.add_argument("-a", "--apply", action="store_true", help="Apply changes (default: dry-run)")
    args = parser.parse_args()
    ref_path = Path(args.reference)
    if not ref_path.exists():
        print(f"❌ Reference file not found: {ref_path}")
        sys.exit(1)
    if ref_path.suffix != ".py":
        print("❌ Reference must be a .py file")
        sys.exit(1)
    print(f"📖 Analyzing reference: {ref_path}")
    ref_funcs = extract_top_level_functions(ref_path)
    if ref_funcs is None:
        print("❌ Failed to parse reference file")
        sys.exit(1)
    if not ref_funcs:
        print("⚠️  No functions found in reference")
        sys.exit(1)
    ref_hashes = {info["hash"]: info["name"] for info in ref_funcs.values()}
    print(f"  Found {len(ref_hashes)} functions")
    target_files = expand_input_paths(args.inputs)
    target_files = [f for f in target_files if f != ref_path]
    if not target_files:
        print("⚠️  No target files found")
        sys.exit(0)
    mode = "applying" if args.apply else "scanning"
    print(f"\n🔍 {mode} {len(target_files)} file(s)...")
    print("-" * 40)
    total_duplicates = 0
    total_updated = 0
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = executor.map(lambda f: process_target_file(f, ref_hashes, args.apply), target_files)
        for result in results:
            if result["status"] == "skipped":
                print(f"⊘  {result['file']}")
            elif result["status"] == "ok":
                print(f"✅ {result['file']}")
            elif result["status"] == "found":
                total_duplicates += len(result["duplicates"])
                names = ", ".join(d["name"] for d in result["duplicates"])
                print(f"⚠️  {result['file']}: {names}")
            elif result["status"] == "updated":
                total_updated += len(result["duplicates"])
                names = ", ".join(result["duplicates"])
                print(f"✂️  {result['file']}: removed {names}")
            elif result["status"] == "error":
                print(f"❌ {result['file']}: {result['error']}")
    print("-" * 40)
    if args.apply:
        print(f"✅ Removed {total_updated} duplicate(s)")
    else:
        print(f"ℹ️  Found {total_duplicates} duplicate function(s)")
        print("   Run with -a/--apply to remove")


if __name__ == "__main__":
    raise SystemExit(main())
