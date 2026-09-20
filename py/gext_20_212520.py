from __future__ import annotations
import argparse
import ast
import concurrent.futures
import os
from pathlib import Path
import re
import sys
from typing import List, Tuple, Dict

OUTPUT_SUBDIRS = {"class": "classes", "function": "func", "const": "const"}


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


def extract_top_level_entities_from_text(text: str, relpath: str) -> list[tuple[str, str, int, str]]:
    try:
        tree = ast.parse(text, filename=relpath)
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


def write_entity(out_dir: Path, kind: str, name: str, relpath: str, lineno: int, src: str) -> Path:
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
    return target_path


def process_file(file_path: Path, roots: list[Path], out_dir: Path) -> dict:
    try:
        text = file_path.read_text(encoding="utf-8")
    except Exception as e:
        return {"file": str(file_path), "error": f"read_error: {e}"}

    rel = None
    for r in roots:
        try:
            rel = str(file_path.relative_to(r))
            break
        except Exception:
            continue
    if rel is None:
        rel = str(file_path.name)

    entities = extract_top_level_entities_from_text(text, rel)
    written: list[Path] = []
    counts = {"class": 0, "function": 0, "const": 0}

    for kind, name, lineno, src in entities:
        p = write_entity(out_dir, kind, name, rel, lineno, src)
        written.append(p)
        counts[kind] = counts.get(kind, 0) + 1

    return {"file": rel, "counts": counts, "written": written}


def gather_py_files(roots: list[Path], out_dir: Path) -> list[Path]:
    files = []
    seen = set()
    for r in roots:
        for p in r.rglob("*.py"):
            p_res = p.resolve()
            if p_res in seen:
                continue
            try:
                if out_dir.resolve() in p_res.parents or p_res == out_dir.resolve():
                    continue
            except Exception:
                pass
            seen.add(p_res)
            files.append(p_res)
    return files


def print_pretty_report(per_file_reports: list[dict], out_dir: Path):
    print()
    print("Extraction report".center(80, "="))
    total = {"class": 0, "function": 0, "const": 0, "files": 0}
    for rep in per_file_reports:
        if "error" in rep:
            print(f"- {rep['file']}: ERROR: {rep['error']}")
            continue
        counts = rep["counts"]
        total["class"] += counts.get("class", 0)
        total["function"] += counts.get("function", 0)
        total["const"] += counts.get("const", 0)
        total["files"] += 1

        file_line = f"{rep['file']}"
        counts_line = (
            f"classes={counts.get('class', 0)}  funcs={counts.get('function', 0)}  consts={counts.get('const', 0)}"
        )
        print(f"{file_line}")
        print(f"  {counts_line}")
        if rep.get("written"):
            for w in rep["written"]:
                try:
                    wr = w.relative_to(out_dir)
                except Exception:
                    wr = w
                print(f"    -> {wr}")
        print("-" * 80)

    print()
    print("Totals".center(80, "-"))
    print(f"Files with extractions: {total['files']}")
    print(f"Total classes:   {total['class']}")
    print(f"Total functions: {total['function']}")
    print(f"Total constants: {total['const']}")
    print(f"Output directory: {out_dir.resolve()}")
    print("=" * 80)
    print()


def parse_args():
    p = argparse.ArgumentParser(description="Extract top-level classes, functions, and constants from .py files.")
    p.add_argument(
        "roots",
        nargs="*",
        type=Path,
        help="One or more root directories to scan (default: current directory).",
    )
    p.add_argument(
        "--out",
        "-o",
        type=Path,
        default=Path("output"),
        help="Output directory (default: ./output).",
    )
    p.add_argument(
        "--workers",
        "-j",
        type=int,
        default=max(2, (os.cpu_count() or 2)),
        help="Number of worker threads for parallel processing (default: number of CPUs).",
    )
    return p.parse_args()


def main():
    args = parse_args()
    roots = args.roots or [Path(".")]
    roots = [r.resolve() for r in roots]
    out_dir = args.out.resolve()
    workers = max(1, args.workers)

    for r in roots:
        if not r.exists() or not r.is_dir():
            print(f"Root directory not found or not a directory: {r}", file=sys.stderr)
            sys.exit(2)

    print(f"Scanning {', '.join(str(r) for r in roots)} with {workers} workers...")
    py_files = gather_py_files(roots, out_dir)

    if not py_files:
        print("No .py files found.")
        return

    per_file_reports: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as exe:
        futures = {exe.submit(process_file, p, roots, out_dir): p for p in py_files}
        for fut in concurrent.futures.as_completed(futures):
            try:
                rep = fut.result()
            except Exception as e:
                p = futures[fut]
                rep = {"file": str(p), "error": f"processing_error: {e}"}
            per_file_reports.append(rep)

    per_file_reports.sort(key=lambda r: r.get("file", ""))

    print_pretty_report(per_file_reports, out_dir)


if __name__ == "__main__":
    main()
