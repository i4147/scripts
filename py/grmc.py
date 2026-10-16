from __future__ import annotations

import argparse
import ast
import io
import tokenize
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from loguru import logger

SKIP_DIRS = {".git", "__pycache__", ".ruff_cache", ".pytest_cache"}


def get_removal_zones(source: str):
    tree = ast.parse(source)
    zones = []
    replacements = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            ds_node = node.body[0]
            start_line, start_col = ds_node.lineno - 1, ds_node.col_offset
            end_line, end_col = ds_node.end_lineno - 1, ds_node.end_col_offset
            if len(node.body) == 1:
                replacements.append(((start_line, start_col), "pass"))
            else:
                zones.append((start_line, start_col, end_line, end_col))
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            content = tok.string
            start_line, start_col = tok.start
            end_line, end_col = tok.end
            if start_line == 1 and start_col == 0 and content.startswith("#!"):
                continue
            if "# fmt" in content or "# type" in content:
                continue
            zones.append((start_line, start_col, end_line, end_col))
    return zones, replacements


def apply_cleaning(source: str, zones, replacements):
    lines = source.splitlines(keepends=True)
    for start_l, start_c, end_l, end_c in zones:
        if start_l == end_l:
            lines[start_l] = lines[start_l][:start_c] + lines[start_l][end_c:]
        else:
            lines[start_l] = lines[start_l][:start_c]
            for l in range(start_l + 1, end_l):
                lines[l] = ""
            lines[end_l] = lines[end_l][end_c:]
    for (line_idx, col_idx), text in replacements:
        lines[line_idx] = lines[line_idx][:col_idx] + text + lines[line_idx][col_idx:]
    return "".join(lines)


def is_python_script(path: Path) -> bool:
    if path.suffix == ".py":
        return True
    try:
        with path.open("r") as f:
            first_line = f.readline()
            return first_line.startswith("#!") and "python" in first_line.lower()
    except Exception:
        return False


def process_file(args):
    path, root = args
    try:
        rel_path = path.relative_to(root)
        source = path.read_text()
        zones, replacements = get_removal_zones(source)
        cleaned_code = apply_cleaning(source, zones, replacements)
        ast.parse(cleaned_code)
        removed_count = len(zones) + len(replacements)
        if removed_count > 0:
            path.write_text(cleaned_code)
            logger.info(f"{rel_path}: removed {removed_count} elements")
            return removed_count
        return 0
    except Exception as e:
        logger.error(f"Failed {path}: {e}")
        return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("targets", nargs="*", type=str)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    targets = [Path(t).resolve() for t in args.targets] if args.targets else [root]
    files_to_process = []
    for target in targets:
        if target.is_symlink():
            continue
        if target.is_file():
            if not any(part in SKIP_DIRS for part in target.parts) and is_python_script(target):
                files_to_process.append((target, root))
        elif target.is_dir():
            for path in target.rglob("*"):
                if path.is_symlink():
                    continue
                if path.is_file() and not any(part in SKIP_DIRS for part in path.parts):
                    if is_python_script(path):
                        files_to_process.append((path.resolve(), root))
    with ProcessPoolExecutor() as executor:
        results = list(executor.map(process_file, files_to_process))
    total_removed = sum(results)
    logger.success(f"Cleanup complete. Total elements removed: {total_removed}")


if __name__ == "__main__":
    raise SystemExit(main())
