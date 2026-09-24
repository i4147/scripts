from __future__ import annotations
import ast
import io
import sys
from pathlib import Path
from typing import List, Tuple, Optional, Dict
import tokenize
import concurrent.futures
import multiprocessing

try:
    import astor
except Exception:
    print("This script requires the 'astor' package. Install with: pip install astor", file=sys.stderr)
    sys.exit(2)


class DocstringStripper(ast.NodeTransformer):
    def __init__(self):
        self.is_module_docstring = True

    def visit_Module(self, node: ast.Module) -> ast.AST:
        self.is_module_docstring = True
        if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
            if isinstance(node.body[0].value.value, str):
                self.is_module_docstring = False
                self.generic_visit(node)
                self.is_module_docstring = True
                return node
        self.generic_visit(node)
        return node

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
    for i, line in enumerate(lines):
        stripped = line.strip()
        if i == 0 and line.startswith("#!"):
            prefix_lines.append(line)
            continue
        if stripped == "":
            if prefix_lines:
                prefix_lines.append(line)
            continue
        if stripped.startswith("#"):
            low = stripped.lower()
            if "coding" in low or "encoding" in low or "type:" in low or ("fmt:" in low):
                prefix_lines.append(line)
                continue
            continue
        break
    prefix = "".join(prefix_lines)
    remainder = "".join(lines[i:]) if i < len(lines) else ""
    return (prefix, remainder)


def collect_preserved_inline_comments(source: str) -> Dict[int, List[str]]:
    comments_by_line: Dict[int, List[str]] = {}
    sio = io.StringIO(source)
    try:
        for tok in tokenize.generate_tokens(sio.readline):
            if tok.type == tokenize.COMMENT:
                tok_string = tok.string
                low = tok_string.lower()
                if "type:" in low or "fmt:" in low:
                    start_row = tok.start[0]
                    comments_by_line.setdefault(start_row, []).append(tok_string)
    except tokenize.TokenError:
        pass
    return comments_by_line


def reattach_inline_comments(new_source: str, preserved_comments: Dict[int, List[str]]) -> str:
    if not preserved_comments:
        return new_source
    new_lines = new_source.splitlines()
    max_line = len(new_lines)
    attached = set()
    for orig_line_no in sorted(preserved_comments.keys()):
        target_idx = orig_line_no - 1
        if 0 <= target_idx < max_line:
            for comment in preserved_comments[orig_line_no]:
                line = new_lines[target_idx]
                if comment not in line:
                    if line.rstrip():
                        new_lines[target_idx] = line + "  " + comment
                    else:
                        new_lines[target_idx] = comment
                attached.add((orig_line_no, comment))
    for orig_line_no in sorted(preserved_comments.keys()):
        for comment in preserved_comments[orig_line_no]:
            if (orig_line_no, comment) not in attached:
                new_lines.append(comment)
    result = "\n".join(new_lines)
    if new_source.endswith("\n") and (not result.endswith("\n")):
        result += "\n"
    return result


def process_file(path: Path) -> Tuple[str, bool, Optional[str]]:
    try:
        with tokenize.open(path) as f:
            original = f.read()
            encoding = f.encoding
    except Exception as exc:
        return (str(path), False, f"read-error: {exc}")
    if not original.strip():
        return (str(path), False, None)
    preserved_inline_comments = collect_preserved_inline_comments(original)
    prefix, _ = extract_prefix_comments_and_shebang(original)
    try:
        tree = ast.parse(original)
    except SyntaxError as exc:
        return (str(path), False, f"syntax-error-original: {exc}")
    stripper = DocstringStripper()
    new_tree = stripper.visit(tree)
    ast.fix_missing_locations(new_tree)
    try:
        new_source = astor.to_source(new_tree)
    except Exception as exc:
        return (str(path), False, f"unparse-failed: {exc}")
    parts = []
    if prefix:
        parts.append(prefix)
    parts.append(new_source)
    combined = "".join(parts)
    combined = reattach_inline_comments(combined, preserved_inline_comments)
    combined = combined.rstrip("\n") + "\n"
    try:
        ast.parse(combined)
    except SyntaxError as exc:
        return (str(path), False, f"syntax-error-transformed: {exc}")
    if combined == original:
        return (str(path), False, None)
    try:
        with open(path, "w", encoding=encoding, newline="\n") as f:
            f.write(combined)
    except Exception as exc:
        return (str(path), False, f"write-error: {exc}")
    return (str(path), True, None)


def should_skip_path(p: Path) -> bool:
    parts = {part.lower() for part in p.parts}
    skip_indicators = {".git", "__pycache__", ".venv", "venv", "node_modules"}
    return bool(parts & skip_indicators)


def collect_py_files(cwd: Path) -> List[Path]:
    files: List[Path] = []
    for p in cwd.rglob("*.py"):
        if should_skip_path(p) or p.is_symlink():
            continue
        files.append(p)
    return files


def main() -> int:
    cwd = Path.cwd()
    files = collect_py_files(cwd)
    if not files:
        print("No .py files found.")
        return 0
    changed: List[str] = []
    errors: List[Tuple[str, str]] = []
    workers = max(1, min(32, multiprocessing.cpu_count()))
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_file, p): p for p in files}
        for fut in concurrent.futures.as_completed(futures):
            try:
                path_str, did_change, err = fut.result()
                if err:
                    errors.append((path_str, err))
                elif did_change:
                    changed.append(path_str)
            except Exception as exc:
                p = futures[fut]
                errors.append((str(p), f"worker-exception: {exc}"))
    if changed:
        print("Files changed:")
        for p in sorted(changed):
            print(f"  {p}")
    else:
        print("No files were changed.")
    if errors:
        print("\nFiles with errors (left unchanged):")
        for p, e in sorted(errors):
            print(f"  {p}: {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
