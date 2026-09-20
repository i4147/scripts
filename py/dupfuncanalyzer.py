from __future__ import annotations

import argparse
import ast
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any


def get_source(node: ast.AST, content: str) -> str:
    return ast.get_source_segment(content, node) or ""


def normalize_source(source: str) -> str:
    if not source:
        return ""
    return "\n".join(line.rstrip() for line in source.strip().splitlines())


def analyze_file(file_path: Path) -> dict[str, list[str]]:
    definitions = defaultdict(list)
    source_map = {}
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                source = get_source(node, content)
                norm = normalize_source(source)
                key = (node.name, norm)
                definitions[key].append(str(file_path))
                if key not in source_map:
                    source_map[key] = source
    except Exception:
        pass
    return {"definitions": dict(definitions), "source_map": dict(source_map)}


def analyze_files(target_dirs: list[Path] | None = None) -> list[dict[str, Any]]:
    if not target_dirs:
        target_dirs = [Path.cwd()]
    py_files = []
    for target_dir in target_dirs:
        py_files.extend(target_dir.rglob("*.py"))
    py_files = [f for f in py_files if ".git" not in f.parts]
    definitions = defaultdict(list)
    source_map = {}
    with ProcessPoolExecutor() as executor:
        results = executor.map(analyze_file, py_files)
    for result in results:
        for key, paths in result["definitions"].items():
            definitions[key].extend(paths)
        source_map.update(result["source_map"])
    repeated = []
    for key, paths in definitions.items():
        unique_paths = list(set(paths))
        if len(unique_paths) >= 2:
            repeated.append(
                {
                    "name": key[0],
                    "source": source_map.get(key, ""),
                    "count": len(unique_paths),
                    "files": unique_paths,
                }
            )
    repeated.sort(key=lambda x: x["count"], reverse=True)
    return repeated


def save_dh_module(repeated: list[dict[str, Any]], output_path: Path = Path("repeated_functions.py")) -> None:
    lines = []
    for item in repeated:
        lines.append(item["source"])
        lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def apply_refactoring(repeated: list[dict[str, Any]], target_dirs: list[Path] | None = None) -> None:
    if not target_dirs:
        target_dirs = [Path.cwd()]
    py_files = []
    for target_dir in target_dirs:
        py_files.extend(target_dir.rglob("*.py"))
    py_files = [f for f in py_files if ".git" not in f.parts and f.name != "repeated_functions.py"]
    with ProcessPoolExecutor() as executor:
        executor.map(lambda f: refactor_file(f, repeated), py_files)


def refactor_file(file_path: Path, repeated: list[dict[str, Any]]) -> None:
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content)
    except Exception:
        return
    imports_to_add = set()
    lines = content.splitlines(keepends=True)
    nodes_to_remove = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            for item in repeated:
                if node.name == item["name"]:
                    source = get_source(node, content)
                    if normalize_source(source) == normalize_source(item["source"]):
                        imports_to_add.add(item["name"])
                        nodes_to_remove.append(node)
    if not imports_to_add:
        return
    lines_to_keep = []
    for i, line in enumerate(lines):
        skip = False
        for node in nodes_to_remove:
            if node.lineno and node.end_lineno and node.lineno - 1 <= i < node.end_lineno:
                skip = True
                break
        if not skip:
            lines_to_keep.append(line)
    import_stmt = "from dh import " + ", ".join(sorted(imports_to_add)) + "\n"
    insert_pos = 0
    for i, line in enumerate(lines_to_keep):
        if line.strip() and not line.strip().startswith("#"):
            insert_pos = i
            break
    lines_to_keep.insert(insert_pos, import_stmt)
    file_path.write_text("".join(lines_to_keep), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect and refactor duplicate functions")
    parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="Apply refactoring: remove duplicates and add imports",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Directories or files to process (default: current directory)",
    )
    args = parser.parse_args()
    target_dirs = [Path(p) for p in args.paths] if args.paths else None
    repeated = analyze_files(target_dirs)
    save_dh_module(repeated)
    if args.apply:
        apply_refactoring(repeated, target_dirs)
        print(f"Saved {len(repeated)} functions to repeated_functions.py")
    else:
        print(f"Found {len(repeated)} repeated functions. Saved")


if __name__ == "__main__":
    raise SystemExit(main())
