from __future__ import annotations
import ast
import argparse
import os
from pathlib import Path
import re
import sys
from typing import List, Tuple

OUTPUT_SUBDIRS = {
    "class": "classes",
    "function": "func",
    "const": "const",
}


def sanitize_for_filename(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]", "_", s)


def get_source_segment(src: str, node: ast.AST) -> str:
    try:
        seg = ast.get_source_segment(src, node)
        if seg:
            return seg
    except Exception:
        pass

    lines = src.splitlines(keepends=True)
    lineno = getattr(node, "lineno", None)
    end_lineno = getattr(node, "end_lineno", None)
    if lineno is not None and end_lineno is not None:
        return "".join(lines[lineno - 1 : end_lineno])
    if lineno is not None:
        return lines[lineno - 1]
    return ""


def is_top_level_constant(node: ast.AST) -> list[str]:
    names = []
    if isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id.isupper():
                names.append(t.id)
    elif isinstance(node, ast.AnnAssign):
        t = node.target
        if isinstance(t, ast.Name) and t.id.isupper():
            names.append(t.id)
    return names


def extract_top_level_entities_from_file(path: Path) -> list[tuple[str, str, int, str]]:
    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []

    results: list[tuple[str, str, int, str]] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            name = node.name
            lineno = getattr(node, "lineno", 0)
            src = get_source_segment(text, node)
            results.append(("class", name, lineno, src))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
            lineno = getattr(node, "lineno", 0)
            src = get_source_segment(text, node)
            results.append(("function", name, lineno, src))
        else:
            const_names = is_top_level_constant(node)
            if const_names:
                lineno = getattr(node, "lineno", 0)
                src = get_source_segment(text, node)
                for cname in const_names:
                    results.append(("const", cname, lineno, src))
    return results


def write_entity(out_dir: Path, kind: str, name: str, relpath: str, lineno: int, src: str):
    subdir = OUTPUT_SUBDIRS.get(kind, kind)
    target_dir = out_dir / subdir
    target_dir.mkdir(parents=True, exist_ok=True)

    safe_name = sanitize_for_filename(name)
    safe_rel = sanitize_for_filename(relpath)
    filename = f"{safe_name}__{safe_rel}__L{lineno}.py"
    target_path = target_dir / filename

    header = f"# extracted {kind} {name} from {relpath}:{lineno}\n"
    content = header + src
    target_path.write_text(content, encoding="utf-8")


def scan_and_extract(root: Path, out_dir: Path, ignore_out_dir: bool = True):
    root = root.resolve()
    out_dir = out_dir.resolve()
    summary = {"class": 0, "function": 0, "const": 0, "files": 0}
    for dirpath, dirnames, filenames in os.walk(root):
        if ignore_out_dir and (out_dir == Path(dirpath) or out_dir in Path(dirpath).parents):
            continue
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            file_path = Path(dirpath) / fname
            rel = str(file_path.relative_to(root))
            entities = extract_top_level_entities_from_file(file_path)
            if entities:
                summary["files"] += 1
            for kind, name, lineno, src in entities:
                write_entity(out_dir, kind, name, rel, lineno, src)
                summary[kind] = summary.get(kind, 0) + 1
    return summary


def parse_args():
    p = argparse.ArgumentParser(description="Extract top-level classes, functions, and constants from .py files.")
    p.add_argument(
        "--root",
        "-r",
        type=Path,
        default=Path("."),
        help="Root directory to scan (default: current directory).",
    )
    p.add_argument(
        "--out",
        "-o",
        type=Path,
        default=Path("output"),
        help="Output directory (default: ./output).",
    )
    return p.parse_args()


def main():
    args = parse_args()
    root = args.root
    out = args.out

    if not root.exists() or not root.is_dir():
        print(f"Root directory not found: {root}", file=sys.stderr)
        sys.exit(2)

    print(f"Scanning {root} for .py files...")
    summary = scan_and_extract(root, out)
    print(f"Done. Files scanned with extractions: {summary['files']}")
    print(f"Classes: {summary.get('class', '0')}")
    print(f"Functions: {summary.get('function', '0')}")
    print(f"Constants: {summary.get('const', '0')}")
    print(f"Output written under {out.resolve()}")


if __name__ == "__main__":
    main()
