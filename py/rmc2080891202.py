from __future__ import annotations

import argparse
import ast
import shutil
import sys
import tempfile
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileResult:
    path: str
    comments_removed: int = 0
    docstrings_removed: int = 0
    changed: bool = False
    error: str | None = None


@dataclass
class Summary:
    total: int = 0
    changed: int = 0
    comments: int = 0
    docstrings: int = 0
    errors: int = 0
    error_files: list[str] = field(default_factory=list)


_PRESERVE_PREFIXES = ("#!", "# -*-", "# coding", "# type:", "# noqa", "# pragma:")


def _strip_comments(source: str) -> tuple[str, int]:
    lines = source.splitlines(keepends=True)
    result: list[str] = []
    removed = 0
    in_triple: str | None = None
    in_string: str | None = None
    escape_next = False
    for line in lines:
        new_line_chars: list[str] = []
        i = 0
        length = len(line)
        while i < length:
            ch = line[i]
            if in_triple is not None:
                new_line_chars.append(ch)
                closing = in_triple * 3
                if line[i : i + 3] == closing:
                    new_line_chars.append(line[i + 1])
                    new_line_chars.append(line[i + 2])
                    in_triple = None
                    i += 3
                    continue
                i += 1
                continue
            if in_string is not None:
                if escape_next:
                    escape_next = False
                    new_line_chars.append(ch)
                    i += 1
                    continue
                if ch == "\\":
                    escape_next = True
                    new_line_chars.append(ch)
                    i += 1
                    continue
                if ch == in_string:
                    in_string = None
                new_line_chars.append(ch)
                i += 1
                continue
            if ch in ('"', "'") and line[i : i + 3] == ch * 3:
                in_triple = ch
                new_line_chars.extend([ch, ch, ch])
                i += 3
                continue
            if ch in ('"', "'"):
                in_string = ch
                new_line_chars.append(ch)
                i += 1
                continue
            if ch == "#":
                rest = line[i:]
                stripped_rest = rest.strip()
                if any(
                    stripped_rest.startswith(p.lstrip("#").strip()) or rest.lstrip().startswith(p)
                    for p in _PRESERVE_PREFIXES
                ):
                    new_line_chars.append(rest)
                    i = length
                    continue
                inline_prefix = "".join(new_line_chars).rstrip()
                eol = "\n" if line.endswith("\n") else ""
                if inline_prefix:
                    new_line_chars = list(inline_prefix + eol)
                    removed += 1
                else:
                    new_line_chars = [eol] if eol else []
                    removed += 1
                i = length
                continue
            new_line_chars.append(ch)
            i += 1
        result.append("".join(new_line_chars))
    return ("".join(result), removed)


class _DocstringRemover(ast.NodeTransformer):
    def __init__(self, remove_module: bool = False) -> None:
        self.remove_module = remove_module
        self.count = 0

    def _strip_docstring(self, node: ast.AST, is_module: bool = False) -> ast.AST:
        if is_module and (not self.remove_module):
            return node
        body = getattr(node, "body", [])
        if not body:
            return node
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            self.count += 1
            new_body = body[1:]
            if not new_body:
                new_body = [ast.Pass()]
            node.body = new_body
        return node

    def visit_Module(self, node: ast.Module) -> ast.AST:
        self.generic_visit(node)
        return self._strip_docstring(node, is_module=True)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        self.generic_visit(node)
        return self._strip_docstring(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        self.generic_visit(node)
        return self._strip_docstring(node)


def _remove_docstrings(source: str, remove_module: bool) -> tuple[str, int]:
    tree = ast.parse(source)
    remover = _DocstringRemover(remove_module=remove_module)
    new_tree = remover.visit(tree)
    ast.fix_missing_locations(new_tree)
    return (ast.unparse(new_tree), remover.count)


def _extract_header(lines: list[str]):
    header: list[str] = []
    idx = 0
    for i, line in enumerate(lines[:2]):
        stripped = line.strip()
        if i == 0 and stripped.startswith("#!"):
            header.append(line)
            idx = i + 1
        elif stripped.startswith(("# -*-", "# coding")):
            header.append(line)
            idx = i + 1
        else:
            break
    return (header, lines[idx:])


def process_file(
    path: str | Path, remove_module_docstring: bool = False, dry_run: bool = False, display_path: str | None = None
) -> FileResult:
    path = Path(path)
    label = display_path or str(path)
    result = FileResult(path=label)
    try:
        original = path.read_text(encoding="utf-8")
    except Exception as exc:
        result.error = f"Read error: {exc}"
        return result
    try:
        comment_cleaned, n_comments = _strip_comments(original)
    except Exception as exc:
        result.error = f"Comment stripping failed: {exc}"
        return result
    try:
        final_source, n_docs = _remove_docstrings(comment_cleaned, remove_module_docstring)
    except SyntaxError as exc:
        result.error = f"Syntax error during AST parse: {exc}"
        return result
    except Exception as exc:
        result.error = f"Docstring removal failed: {exc}"
        return result
    result.comments_removed = n_comments
    result.docstrings_removed = n_docs
    if final_source.strip() == original.strip():
        return result
    try:
        ast.parse(final_source)
    except SyntaxError as exc:
        result.error = f"Output validation failed: {exc}"
        return result
    result.changed = True
    if dry_run:
        return result
    tmp_path: Path | None = None
    try:
        fd, tmp_str = tempfile.mkstemp(dir=path.parent, suffix=".tmp.py", prefix=path.stem + "_")
        tmp_path = Path(tmp_str)
        with open(fd, "w", encoding="utf-8") as fh:
            fh.write(final_source)
        shutil.move(str(tmp_path), str(path))
        tmp_path = None
    except Exception as exc:
        result.error = f"Write error: {exc}"
        result.changed = False
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
    return result


def _dry_run_process(path: str, remove_module: bool) -> FileResult:
    return process_file(path, remove_module_docstring=remove_module, dry_run=True)


def _live_process(path: str, remove_module: bool) -> FileResult:
    return process_file(path, remove_module_docstring=remove_module, dry_run=False)


def process_wheel(whl_path: Path, remove_module_docstring: bool = False, dry_run: bool = False) -> list[FileResult]:
    results: list[FileResult] = []
    whl_name = whl_path.name
    tmp_dir = Path(tempfile.mkdtemp(prefix="pystrip_whl_"))
    try:
        try:
            with zipfile.ZipFile(whl_path, "r") as zf:
                zf.extractall(tmp_dir)
                members = zf.namelist()
        except Exception as exc:
            results.append(FileResult(path=whl_name, error=f"Cannot open wheel: {exc}"))
            return results
        any_changed = False
        for member in members:
            if not member.endswith(".py"):
                continue
            member_path = tmp_dir / member
            if not member_path.is_file():
                continue
            virtual = f"{whl_name}::{member}"
            r = process_file(
                member_path, remove_module_docstring=remove_module_docstring, dry_run=dry_run, display_path=virtual
            )
            results.append(r)
            if r.changed:
                any_changed = True
        if any_changed and (not dry_run):
            tmp_whl = whl_path.with_suffix(".tmp.whl")
            try:
                with zipfile.ZipFile(tmp_whl, "w", zipfile.ZIP_DEFLATED) as zout:
                    for member in members:
                        member_path = tmp_dir / member
                        if member_path.is_file():
                            zout.write(member_path, member)
                shutil.move(str(tmp_whl), str(whl_path))
            except Exception as exc:
                tmp_whl.unlink(missing_ok=True)
                results.append(FileResult(path=whl_name, error=f"Failed to rebuild wheel: {exc}"))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return results


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".venv",
        "venv",
        "lazy",
        ".tox",
        "dist",
        "build",
        ".eggs",
    }
)


def discover_files(root: Path) -> tuple[list[Path], list[Path]]:
    if root.is_file():
        if root.suffix == ".py":
            return ([root], [])
        if root.suffix == ".whl":
            return ([], [root])
        return ([], [])
    py_files: list[Path] = []
    whl_files: list[Path] = []
    for dirpath, dirs, files in root.walk(top_down=True):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fname in files:
            fp = dirpath / fname
            if fp.suffix == ".py":
                py_files.append(fp)
            elif fp.suffix == ".whl":
                whl_files.append(fp)
    return (py_files, whl_files)


def _print_result(r: FileResult, root: Path) -> None:
    try:
        label = Path(r.path).relative_to(root)
    except ValueError:
        label = r.path
    if r.error:
        print(f"  {label} (error: {r.error})")
    elif not r.changed and r.comments_removed == 0 and (r.docstrings_removed == 0):
        pass
    else:
        parts: list[str] = []
        if r.comments_removed:
            parts.append(f"{r.comments_removed} comment{('s' if r.comments_removed != 1 else '')}")
        if r.docstrings_removed:
            parts.append(f"{r.docstrings_removed} docstring{('s' if r.docstrings_removed != 1 else '')}")
        if parts:
            suffix = ", ".join(parts) + " removed"
        else:
            suffix = "no change"
        print(f"  {label} ({suffix})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Strip comments and docstrings from Python source files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "target", nargs="?", default=".", help="File or directory to process (default: current directory)"
    )
    parser.add_argument(
        "--workers", type=int, default=4, metavar="N", help="Number of parallel worker processes (default: 4)"
    )
    parser.add_argument("--remove-module-docstring", action="store_true", help="Also remove module-level docstrings")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without modifying files")
    args = parser.parse_args(argv)
    root = Path(args.target).resolve()
    if not root.exists():
        print(f"Error: '{root}' does not exist.", file=sys.stderr)
        return 1
    py_files, whl_files = discover_files(root)
    print(
        f"Found: {len(py_files)} Python file{('s' if len(py_files) != 1 else '')}, {len(whl_files)} wheel file{('s' if len(whl_files) != 1 else '')}\n"
    )
    summary = Summary()
    remove_module = args.remove_module_docstring
    dry_run = args.dry_run
    worker_fn = _dry_run_process if dry_run else _live_process
    if py_files:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(worker_fn, str(fp), remove_module): fp for fp in py_files}
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception as exc:
                    fp = futures[future]
                    result = FileResult(path=str(fp), error=f"Unexpected: {exc}")
                summary.total += 1
                if result.error:
                    summary.errors += 1
                    summary.error_files.append(result.path)
                if result.changed:
                    summary.changed += 1
                summary.comments += result.comments_removed
                summary.docstrings += result.docstrings_removed
                _print_result(result, root)
    for whl in whl_files:
        print(f"\nProcessing wheel: {whl.name}")
        whl_results = process_wheel(whl, remove_module, dry_run)
        for r in whl_results:
            summary.total += 1
            if r.error:
                summary.errors += 1
                summary.error_files.append(r.path)
            if r.changed:
                summary.changed += 1
            summary.comments += r.comments_removed
            summary.docstrings += r.docstrings_removed
            _print_result(r, root)
    print("\n" + "=" * 50)
    print("Summary:")
    print(f"  Total files processed : {summary.total}")
    print(f"  Files changed         : {summary.changed}")
    print(f"  Comments removed      : {summary.comments}")
    print(f"  Docstrings removed    : {summary.docstrings}")
    if summary.errors:
        print(f"  Errors                : {summary.errors}")
        for ef in summary.error_files:
            print(f"    - {ef}")
    if dry_run:
        print("\n  (dry-run: no files were modified)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
