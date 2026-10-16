from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

DH_DIR = Path.home() / "projects/py/dh/src/dh"


def hash_string(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def extract_function_index(dh_dir: Path) -> dict[str, str]:
    index: dict[str, str] = {}
    if not dh_dir.exists():
        raise SystemExit(f"dh source directory not found: {dh_dir}")
    for py_file in dh_dir.rglob("*.py"):
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except SyntaxError as e:
            print(f"Warning: syntax error in {py_file}: {e}", file=sys.stderr)
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_source = get_source_segment(source, node)
                h = hash_string(func_source)
                if h in index and index[h] != node.name:
                    print(
                        f"Warning: duplicate hash in dh package for {node.name} (already mapped to {
                            index[h]
                        }). Skipping.",
                        file=sys.stderr,
                    )
                    continue
                index[h] = node.name
    return index


def get_source_segment(source: str, node) -> str:
    lines = source.splitlines(keepends=True)
    start = node.lineno - 1
    end = node.end_lineno
    return "".join(lines[start:end])


def find_import_insert_position(lines: list[str]) -> int:
    pos = 0
    if lines and lines[0].startswith("#!"):
        pos = 1
    last_import = -1
    for i, line in enumerate(lines):
        if re.match("^\\s*(?:from\\s+\\S+\\s+import|import\\s+\\S+)", line):
            last_import = i
    if last_import != -1:
        return last_import + 1
    while pos < len(lines) and lines[pos].strip().startswith("#"):
        pos += 1
    return pos


def process_file(py_file: Path, dh_index: dict[str, str]) -> tuple[Path, list[str], list[str], list[str]] | None:
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except SyntaxError as e:
        print(f"Warning: skipping {py_file}: {e}", file=sys.stderr)
        return None
    lines = source.splitlines(keepends=True)
    matches = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_source = get_source_segment(source, node)
            h = hash_string(func_source)
            if h in dh_index and dh_index[h] == node.name:
                matches.append((node.name, node.lineno, node.end_lineno))
    if not matches:
        return None
    to_remove = set()
    for _, start, end in matches:
        for i in range(start - 1, end):
            to_remove.add(i)
    new_lines = [line for i, line in enumerate(lines) if i not in to_remove]
    import_names = sorted({name for name, _, _ in matches})
    existing_dh_import_idx = -1
    existing_names = set()
    for i, line in enumerate(new_lines):
        m = re.match("^from\\s+dh\\s+import\\s+(.*)", line)
        if m:
            existing_dh_import_idx = i
            existing_names.update(n.strip() for n in m.group(1).split(","))
            break
    names_to_add = [n for n in import_names if n not in existing_names]
    if not names_to_add:
        pass
    elif existing_dh_import_idx != -1:
        old_line = new_lines[existing_dh_import_idx]
        prefix = "from dh import "
        existing_text = old_line[len(prefix) :].strip()
        all_names = sorted(existing_names | set(names_to_add))
        new_lines[existing_dh_import_idx] = prefix + ", ".join(all_names) + "\n"
    else:
        insert_pos = find_import_insert_position(new_lines)
        import_line = "from dh import " + ", ".join(names_to_add) + "\n\n"
        new_lines.insert(insert_pos, import_line)
    return (py_file, lines, new_lines, import_names)


def main():
    parser = argparse.ArgumentParser(description="Replace inlined dh functions with imports.")
    parser.add_argument("-a", "--apply", action="store_true", help="write changes in place")
    args = parser.parse_args()
    dh_index = extract_function_index(DH_DIR)
    here = Path.cwd()
    own_path = Path(sys.argv[0]).resolve()
    py_files = [p for p in here.iterdir() if p.suffix == ".py" and p.resolve() != own_path]
    results: list[tuple[Path, list[str], list[str], list[str]]] = []
    with ProcessPoolExecutor() as executor:
        future_to_path = {executor.submit(process_file, p, dh_index): p for p in py_files}
        for future in as_completed(future_to_path):
            res = future.result()
            if res:
                results.append(res)
    if not results:
        print("No inlined dh functions found.")
        return
    results.sort(key=lambda x: x[0])
    for path, old_lines, new_lines, names in results:
        print(f"\n{'=' * 40}")
        mode = "APPLY" if args.apply else "DRY RUN"
        print(f"[{mode}] {path.name}")
        print(f"  Functions to import from dh: {', '.join(names)}")
        diff = difflib.unified_diff(old_lines, new_lines, fromfile=str(path), tofile=str(path) + " (new)")
        diff_text = "".join(diff)
        if diff_text:
            print(diff_text)
        else:
            print("  (no textual difference)")
        if args.apply:
            path.write_text("".join(new_lines), encoding="utf-8")
            print("  Written.")


if __name__ == "__main__":
    raise SystemExit(main())
