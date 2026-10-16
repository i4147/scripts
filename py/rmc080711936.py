from __future__ import annotations

import argparse
import ast
import io
import os
import re
import sys
import tokenize
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

FMT_PREFIXES = ("# fmt", "# fmt:", "# fmt: off", "# fmt: on")
TYPE_PREFIXES = ("# type", "# type:")


def iter_py_files(inputs: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []

    def add_file(p: Path) -> None:
        try:
            rp = p.resolve()
        except Exception:
            rp = p
        if rp in seen:
            return
        seen.add(rp)
        out.append(p)

    def walk_dir(root: Path):
        root = root
        if root.is_symlink():
            return
        if root.name in {".git", "__pycache__"}:
            return
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dpath = Path(dirpath)
            if dpath.is_symlink():
                continue
            if dpath.name in {".git", "__pycache__"}:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__"}]
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                fp = dpath / fn
                try:
                    if fp.is_symlink():
                        continue
                except Exception:
                    continue
                yield fp

    if not inputs:
        inputs = [Path(".")]

    for inp in inputs:
        inp = inp.expanduser()
        if not inp.exists():
            continue
        if inp.is_symlink():
            continue
        if inp.is_dir():
            for fp in walk_dir(inp):
                add_file(fp)
        elif inp.is_file() and inp.suffix == ".py":
            add_file(inp)

    return out


def line_offsets(text: str) -> list[int]:
    offs = [0]
    for m in re.finditer(r"\n", text):
        offs.append(m.end())
    return offs


def idx_from_lc(line_offsets_: list[int], lineno: int, col: int) -> int:
    if lineno <= 0:
        return 0
    if lineno - 1 >= len(line_offsets_):
        return len(line_offsets_)
    return line_offsets_[lineno - 1] + col


def is_doc_expr_in_stmt(stmt: ast.stmt) -> ast.Expr | None:
    if isinstance(stmt, ast.Expr):
        v = stmt.value
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            return stmt
    return None


def is_func_or_class(node: ast.AST) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))


def compute_docstring_replacements(text: str, remove_module_docstring: bool) -> tuple[str, int, bool]:
    try:
        tree = ast.parse(text, type_comments=True)
    except SyntaxError:
        return text, 0, False

    lo = line_offsets(text)
    replacements: list[tuple[int, int, str]] = []
    docstrings_removed = 0

    if remove_module_docstring and getattr(tree, "body", None):
        first = tree.body[0]
        ds_stmt = is_doc_expr_in_stmt(first)
        if ds_stmt is not None and hasattr(first, "lineno") and hasattr(first, "end_lineno"):
            start = idx_from_lc(lo, first.lineno, first.col_offset)
            end = idx_from_lc(lo, first.end_lineno, first.end_col_offset)
            replacements.append((start, end, ""))
            docstrings_removed += 1

    for node in ast.walk(tree):
        if not is_func_or_class(node):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        ds_stmt = is_doc_expr_in_stmt(first)
        if ds_stmt is None:
            continue
        if not (hasattr(first, "lineno") and hasattr(first, "end_lineno")):
            continue
        start = idx_from_lc(lo, first.lineno, first.col_offset)
        end = idx_from_lc(lo, first.end_lineno, first.end_col_offset)
        repl = "pass" if len(body) == 1 else ""
        replacements.append((start, end, repl))
        docstrings_removed += 1

    if not replacements:
        return text, 0, False

    replacements.sort(key=lambda x: x[0], reverse=True)
    new_text = text
    for s, e, repl in replacements:
        _ = ast.get_source_segment(text, tree)
        new_text = new_text[:s] + repl + new_text[e:]

    if new_text == text:
        return text, 0, False
    try:
        ast.parse(new_text, type_comments=True)
    except SyntaxError:
        return text, 0, False
    return new_text, docstrings_removed, True


def strip_comments_preserve_directives(text: str) -> tuple[str, int, bool]:
    comments_removed = 0
    out_tokens: list[tokenize.TokenInfo] = []

    reader = io.StringIO(text).readline
    try:
        gen = tokenize.generate_tokens(reader)
        for tok in gen:
            if tok.type == tokenize.COMMENT:
                s = tok.string
                if tok.start[0] == 1 and s.startswith("#!"):
                    out_tokens.append(tok)
                    continue
                if any(s.startswith(p) for p in FMT_PREFIXES) or any(s.startswith(p) for p in TYPE_PREFIXES):
                    out_tokens.append(tok)
                    continue
                comments_removed += 1
                continue
            out_tokens.append(tok)
    except tokenize.TokenError:
        return text, 0, False

    if comments_removed == 0:
        return text, 0, False

    new_text = tokenize.untokenize(out_tokens)
    if new_text == text:
        return text, 0, False
    try:
        ast.parse(new_text, type_comments=True)
    except SyntaxError:
        return text, 0, False
    return new_text, comments_removed, True


def process_one(path: Path, remove_module_docstring: bool) -> tuple[Path, int, int, bool]:
    try:
        original = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        original = path.read_text(encoding="utf-8", errors="replace")

    new_text, doc_removed, doc_changed = compute_docstring_replacements(original, remove_module_docstring)

    comm_text = new_text
    if doc_changed:
        comm_text, comments_removed, comm_changed = strip_comments_preserve_directives(comm_text)
    else:
        comm_text, comments_removed, comm_changed = strip_comments_preserve_directives(comm_text)

    if comm_text == original:
        return path, 0, 0, False

    try:
        ast.parse(comm_text, type_comments=True)
    except SyntaxError:
        return path, 0, 0, False

    if not (doc_changed or comm_changed):
        return path, 0, 0, False

    path.write_text(comm_text, encoding="utf-8")
    return path, comments_removed if comm_changed else 0, doc_removed if doc_changed else 0, True


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="*", type=str)
    ap.add_argument("-r", action="store_true", dest="remove_module_docstring")
    ap.add_argument("-j", type=int, default=0, dest="jobs")
    args = ap.parse_args(argv)

    inputs = [Path(x) for x in args.inputs]
    files = iter_py_files(inputs)

    if not files:
        return 0

    jobs = args.jobs
    if jobs <= 0:
        jobs = max(1, (os.cpu_count() or 1) - 1)

    removed_any = False
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        futs = [ex.submit(process_one, p, args.remove_module_docstring) for p in files]
        for fut in as_completed(futs):
            p, c_removed, d_removed, wrote = fut.result()
            if wrote:
                removed_any = True
                print(f"{p}: comments_removed={c_removed} docstrings_removed={d_removed}")
            else:
                print(f"{p}: comments_removed=0 docstrings_removed=0")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
