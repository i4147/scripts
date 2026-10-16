from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

DH_SOURCE_DIR = Path.home() / "projects/py/dh/src/dh"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _node_raw_source(source: str, node) -> str:
    lines = source.splitlines(keepends=True)
    start = node.lineno - 1
    end = node.end_lineno
    return "".join(lines[start:end])


def _detect_newline(lines: list[str]) -> str:
    for line in lines:
        if line.endswith("\r\n"):
            return "\r\n"
        if line.endswith("\n"):
            return "\n"
    return "\n"


def build_dh_index(dh_dir: Path) -> dict[str, str]:
    if not dh_dir.exists():
        raise SystemExit(f"dh source directory not found: {dh_dir}")
    index: dict[str, str] = {}
    for py_file in dh_dir.rglob("*.py"):
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except SyntaxError as exc:
            print(f"warning: syntax error in {py_file}: {exc}", file=sys.stderr)
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_src = _node_raw_source(source, node)
                h = _sha256(func_src)
                if h in index and index[h] != node.name:
                    print(
                        f"warning: hash collision in dh package ({node.name} vs {index[h]}). Keeping first.",
                        file=sys.stderr,
                    )
                    continue
                index[h] = node.name
    return index


def _find_import_insert_point(lines: list[str]) -> int:
    pos = 0
    if lines and lines[0].startswith("#!"):
        pos = 1
    last_import_idx = -1
    for i, line in enumerate(lines):
        if re.match("^\\s*(?:from\\s+\\S+\\s+import|import\\s+\\S+)", line):
            last_import_idx = i
    if last_import_idx != -1:
        return last_import_idx + 1
    while pos < len(lines) and lines[pos].strip().startswith("#"):
        pos += 1
    return pos


def process_file(py_file: Path, dh_index: dict[str, str]):
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except SyntaxError as exc:
        print(f"warning: skipping {py_file}: {exc}", file=sys.stderr)
        return None
    lines = source.splitlines(keepends=True)
    nl = _detect_newline(lines)
    matches = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_src = _node_raw_source(source, node)
            h = _sha256(func_src)
            if h in dh_index and dh_index[h] == node.name:
                matches.append((node.name, node.lineno, node.end_lineno))
    if not matches:
        return None
    to_remove = set()
    for _, start, end in matches:
        for i in range(start - 1, end):
            to_remove.add(i)
    new_lines = [line for i, line in enumerate(lines) if i not in to_remove]
    needed = sorted({name for name, _, _ in matches})
    extended = False
    for i, line in enumerate(new_lines):
        m = re.match(r"^from\s+dh\s+import\s+(.*)", line)
        if not m:
            continue
        present = {n.strip() for n in m.group(1).split(",")}
        combined = sorted(present | set(needed))
        new_lines[i] = "from dh import " + ", ".join(combined) + nl
        extended = True
        break
    if not extended:
        insert_pos = _find_import_insert_point(new_lines)
        import_line = "from dh import " + ", ".join(needed) + nl
        if insert_pos < len(new_lines) and new_lines[insert_pos].strip() != "":
            import_line += nl
        new_lines.insert(insert_pos, import_line)
    return (py_file, lines, new_lines, needed)


def main():
    parser = argparse.ArgumentParser(description="Replace inlined dh functions with proper imports.")
    parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="write changes back to disk (default is dry-run)",
    )
    args = parser.parse_args()
    dh_index = build_dh_index(DH_SOURCE_DIR)
    cwd = Path.cwd()
    own_script = Path(sys.argv[0]).resolve()
    targets = [p for p in cwd.rglob("*.py") if p.resolve() != own_script]
    if not targets:
        print("No Python files found in current directory.")
        return
    results = []
    with ProcessPoolExecutor() as pool:
        futs = {pool.submit(process_file, p, dh_index): p for p in targets}
        for fut in as_completed(futs):
            res = fut.result()
            if res:
                results.append(res)
    if not results:
        print("No inlined dh functions detected.")
        return
    results.sort(key=lambda r: r[0])
    for path, old_lines, new_lines, names in results:
        print(f"\n{'=' * 40}")
        tag = "APPLY" if args.apply else "DRY RUN"
        print(f"[{tag}] {path.name}")
        print(f"  matched functions: {', '.join(names)}")
        diff = difflib.unified_diff(old_lines, new_lines, fromfile=str(path), tofile=str(path) + " (modified)")
        diff_text = "".join(diff)
        if diff_text:
            print(diff_text)
        if args.apply:
            path.write_text("".join(new_lines), encoding="utf-8")
            print("  -> written.")


if __name__ == "__main__":
    raise SystemExit(main())
