from __future__ import annotations
import argparse
import ast
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from dh import get_pyfiles


def _first_statement_is_docstring(tree: ast.Module) -> bool:
    if not tree.body:
        return False
    node = tree.body[0]
    return (
        isinstance(node, ast.Expr)
        and isinstance(getattr(node, "value", None), ast.Constant)
        and isinstance(node.value.value, str)
    )


def _remove_docstrings_from_source(source: str) -> tuple[str, int]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source, 0

    to_remove = []
    preserve_module = _first_statement_is_docstring(tree)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr):
            continue
        val = getattr(node, "value", None)
        if not isinstance(val, ast.Constant) or not isinstance(val.value, str):
            continue

        if preserve_module and tree.body and node is tree.body[0]:
            continue

        if hasattr(node, "lineno") and hasattr(node, "end_lineno"):
            to_remove.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset))

    if not to_remove:
        return source, 0

    lines = source.splitlines(keepends=True)
    to_remove.sort(key=lambda r: (r[0], r[1]), reverse=True)

    for sline, scol, eline, ecol in to_remove:
        sidx = sline - 1
        eidx = eline - 1
        if sidx < 0 or eidx >= len(lines):
            continue

        if sidx == eidx:
            line = lines[sidx]
            lines[sidx] = line[:scol] + "" + line[ecol:]
        else:
            first = lines[sidx]
            last = lines[eidx]
            lines[sidx] = first[:scol]
            lines[eidx] = last[ecol:]
            for mid in range(sidx + 1, eidx):
                lines[mid] = ""

    new_source = "".join(lines)
    return new_source, len(to_remove)


def _validate_syntax(source: str) -> bool:
    try:
        ast.parse(source)
        return True
    except SyntaxError:
        return False


def _collect_py_files(targets: list[Path], recursive: bool = True) -> list[Path]:
    py_files = []
    for target in targets:
        if target.is_file():
            if target.suffix == ".py":
                py_files.append(target)
        elif target.is_dir():
            pattern = "**/*.py" if recursive else "*.py"
            py_files.extend(target.glob(pattern))
    return sorted(set(py_files))


def process_file(path: Path, cwd: Path) -> tuple[str, int] | None:
    rel = str(path.relative_to(cwd))
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        source = path.read_text(encoding="latin-1")
    except Exception as e:
        print(f"ERROR reading {rel}: {e}", flush=True)
        return None

    new_source, count = _remove_docstrings_from_source(source)

    if new_source != source:
        if not _validate_syntax(new_source):
            print(f"VALIDATION FAILED {rel}: output is invalid Python", flush=True)
            return None
        try:
            path.write_text(new_source, encoding="utf-8")
            return (rel, count)
        except Exception as e:
            print(f"ERROR writing {rel}: {e}", flush=True)
            return None

    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Strip docstrings from Python files (preserves module docstrings)")
    parser.add_argument(
        "targets",
        nargs="*",
        help="Files or directories to process (default: current directory, recursive)",
    )
    args = parser.parse_args()

    cwd = Path(".").resolve()

    if args.targets:
        targets = [Path(t).resolve() for t in args.targets]
        py_files = _collect_py_files(targets, recursive=True)
        if not py_files:
            print("No Python files found in targets")
            return
    else:
        py_files = _collect_py_files([cwd], recursive=True)

    results = {}
    with ProcessPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(process_file, p, cwd): p for p in py_files}
        for fut in as_completed(futures):
            result = fut.result()
            if result is not None:
                rel, count = result
                results[rel] = count

    if results:
        for rel in sorted(results.keys()):
            count = results[rel]
            print(f"{rel} ({count} docstring{'s' if count != 1 else ''} removed)")
    else:
        print("No docstrings removed")


if __name__ == "__main__":
    main()
