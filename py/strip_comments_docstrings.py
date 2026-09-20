from __future__ import annotations
import ast
import sys
from pathlib import Path
from typing import List, Tuple, Optional
import tokenize
import concurrent.futures
import multiprocessing


class DocstringStripper(ast.NodeTransformer):
    def _maybe_strip_first_docstring(self, node: ast.AST) -> ast.AST:
        body = getattr(node, "body", None)
        if not body:
            return node
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(getattr(first, "value", None), ast.Constant)
            and isinstance(first.value.value, str)
        ):
            body.pop(0)
            if not body:
                body.append(ast.Pass())
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        self.generic_visit(node)
        return self._maybe_strip_first_docstring(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        self.generic_visit(node)
        return self._maybe_strip_first_docstring(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        self.generic_visit(node)
        return self._maybe_strip_first_docstring(node)


def extract_prefix_comments_and_shebang(source: str) -> Tuple[str, str]:
    lines = source.splitlines(keepends=True)
    prefix_lines: List[str] = []
    i = 0
    seen_any_nonblank = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if i == 0 and line.startswith("#!"):
            prefix_lines.append(line)
            continue
        if stripped == "":
            if prefix_lines:
                prefix_lines.append(line)
            else:
                continue
            continue
        if stripped.startswith("#"):
            low = stripped.lower()
            if (
                "coding" in low
                or "encoding" in low
                or "type:" in low
                or low.startswith("# type")
                or ("fmt:" in low)
                or low.startswith("# fmt")
            ):
                prefix_lines.append(line)
                continue
            continue
        break
    prefix = "".join(prefix_lines)
    remainder = "".join(lines[i:]) if i < len(lines) else ""
    return (prefix, remainder)


def process_file(path: Path) -> Tuple[Path, Optional[str]]:
    try:
        with tokenize.open(path) as f:
            original = f.read()
            encoding = f.encoding
    except Exception as exc:
        return (path, f"read-error: {exc}")
    if not original.strip():
        return (path, None)
    try:
        tree = ast.parse(original)
    except SyntaxError as exc:
        return (path, f"syntax-error-original: {exc}")
    module_docstring = ast.get_docstring(tree, clean=False)
    stripper = DocstringStripper()
    new_tree = stripper.visit(tree)
    ast.fix_missing_locations(new_tree)
    try:
        new_source_body = ast.unparse(new_tree)
    except Exception as exc:
        return (path, f"unparse-failed: {exc}")
    prefix, _ = extract_prefix_comments_and_shebang(original)
    if prefix:
        if not prefix.endswith("\n"):
            prefix = prefix + "\n"
        new_source = prefix + new_source_body
    else:
        new_source = new_source_body
    if not new_source.endswith("\n"):
        new_source = new_source + "\n"
    try:
        ast.parse(new_source)
    except SyntaxError as exc:
        return (path, f"syntax-error-transformed: {exc}")
    if new_source == original:
        return (path, None)
    try:
        with open(path, "w", encoding=encoding, newline="\n") as f:
            f.write(new_source)
    except Exception as exc:
        return (path, f"write-error: {exc}")
    return (path, None)


def should_skip_path(p: Path) -> bool:
    parts = {p_part.lower() for p_part in p.parts}
    skip_indicators = {".git", "__pycache__", "venv", ".venv", "env", ".env", "node_modules"}
    if parts & skip_indicators:
        return True
    return False


def collect_py_files(root: Path) -> List[Path]:
    files: List[Path] = []
    for p in root.rglob("*.py"):
        if should_skip_path(p):
            continue
        if p.is_symlink():
            continue
        files.append(p)
    return files


def main() -> int:
    root = Path(".").resolve()
    files = collect_py_files(root)
    if not files:
        print("No .py files found.")
        return 0
    changed: List[Path] = []
    errors: List[Tuple[Path, str]] = []
    workers = max(1, min(32, multiprocessing.cpu_count()))
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as exc:
        futures = {exc.submit(process_file, p): p for p in files}
        for fut in concurrent.futures.as_completed(futures):
            p = futures[fut]
            try:
                path, err = fut.result()
            except Exception as exc:
                errors.append((p, f"worker-exception: {exc}"))
            else:
                if err is None:
                    pass
                if err:
                    errors.append((path, err))
    changed = []
    errors = []
    for p in files:
        path, err = process_file_check_changed(p)
        if err:
            errors.append((path, err))
        elif path is not None:
            changed.append(path)
    if changed:
        print("Files changed:")
        for p in changed:
            print(f"  {p}")
    else:
        print("No files were changed.")
    if errors:
        print("\nFiles with errors (left unchanged):")
        for p, e in errors:
            print(f"  {p}: {e}")
        return 2
    return 0


def process_file_check_changed(path: Path) -> Tuple[Optional[Path], Optional[str]]:
    try:
        with tokenize.open(path) as f:
            original = f.read()
            encoding = f.encoding
    except Exception as exc:
        return (path, f"read-error: {exc}")
    if not original.strip():
        return (None, None)
    try:
        tree = ast.parse(original)
    except SyntaxError as exc:
        return (path, f"syntax-error-original: {exc}")
    stripper = DocstringStripper()
    new_tree = stripper.visit(tree)
    ast.fix_missing_locations(new_tree)
    try:
        new_source_body = ast.unparse(new_tree)
    except Exception as exc:
        return (path, f"unparse-failed: {exc}")
    prefix, _ = extract_prefix_comments_and_shebang(original)
    if prefix:
        if not prefix.endswith("\n"):
            prefix = prefix + "\n"
        new_source = prefix + new_source_body
    else:
        new_source = new_source_body
    if not new_source.endswith("\n"):
        new_source = new_source + "\n"
    try:
        ast.parse(new_source)
    except SyntaxError as exc:
        return (path, f"syntax-error-transformed: {exc}")
    if new_source != original:
        return (path, None)
    return (None, None)


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
