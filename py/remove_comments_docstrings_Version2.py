from __future__ import annotations
import argparse
import ast
import io
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple
import tokenize

PINNED_TS_VERSION = "0.25.2"
PINNED_TSP_VERSION = "0.25.0"
TREE_SITTER_PARSER = None
TREE_SITTER_LANG = None


def load_tree_sitter() -> Tuple[object, object]:
    try:
        import ts as _ts
        import tsp as _tsp

        v_ts = getattr(_ts, "__version__", None)
        v_tsp = getattr(_tsp, "__version__", None)
        if v_ts is not None and v_ts != PINNED_TS_VERSION:
            raise ImportError(
                f"Installed 'ts' version is {v_ts}; this script was written and tested with ts=={PINNED_TS_VERSION}. Please install the pinned version: pip install ts==0.25.2"
            )
        if v_tsp is not None and v_tsp != PINNED_TSP_VERSION:
            raise ImportError(
                f"Installed 'tsp' version is {v_tsp}; this script was written and tested with tsp=={PINNED_TSP_VERSION}. Please install the pinned version: pip install tsp==0.25.0"
            )
        Parser = getattr(_ts, "Parser")
        for attr in ("language", "PY_LANGUAGE", "PYTHON_LANGUAGE", "LANGUAGE"):
            if hasattr(_tsp, attr):
                PY_LANG = getattr(_tsp, attr)
                return (Parser, PY_LANG)
        return (Parser, _tsp)
    except ImportError:
        raise
    except Exception:
        pass
    try:
        from tree_sitter import Language, Parser

        try:
            import tsp as _tsppkg

            base = Path(_tsppkg.__file__).parent
            candidates = list(base.glob("*.so")) + list(base.glob("*.pyd")) + list(base.glob("*.dylib"))
            py_candidate = None
            for c in candidates:
                if "python" in c.name.lower() or "py" in c.name.lower():
                    py_candidate = c
                    break
            if py_candidate is not None:
                PY_LANG = Language(str(py_candidate), "python")
                return (Parser, PY_LANG)
        except Exception:
            pass
        raise ImportError(
            "tree_sitter Language not found in installed packages. Either install tsp==0.25.0 which bundles a python grammar or compile the tree-sitter-python grammar into a shared library and adjust load_tree_sitter().\n\nExample: pip install ts==0.25.2 tsp==0.25.0\nOr follow: https://tree-sitter.github.io/tree-sitter/using-parsers#installing-parsers"
        )
    except Exception:
        pass
    raise ImportError(
        "Unable to import a compatible tree-sitter binding + python grammar. Try installing: pip install ts==0.25.2 tsp==0.25.0 or pip install tree_sitter and compile tree-sitter-python."
    )


def get_tree_sitter_objects():
    global TREE_SITTER_PARSER, TREE_SITTER_LANG
    if TREE_SITTER_PARSER is None or TREE_SITTER_LANG is None:
        TREE_SITTER_PARSER, TREE_SITTER_LANG = load_tree_sitter()
    return (TREE_SITTER_PARSER, TREE_SITTER_LANG)


def read_source(path: Path) -> Tuple[str, str]:
    with open(path, "rb") as bf:
        encoding, _ = tokenize.detect_encoding(bf.readline)
        bf.seek(0)
        data = bf.read()
        text = data.decode(encoding)
    return (text, encoding)


def write_source(path: Path, text: str, encoding: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as bf:
        bf.write(text.encode(encoding))
    os.replace(tmp, path)


def should_skip_path(p: Path) -> bool:
    skip_dirs = {".git", "__pycache__", "venv", ".venv", "env", "build", "dist", "site-packages"}
    return any((part in skip_dirs for part in p.parts))


@dataclass
class EditRange:
    start: int
    end: int


def tree_sitter_strip(text: str, preserve_module_docstring: bool = True) -> str:
    ParserClass, PY_LANG = get_tree_sitter_objects()
    parser = ParserClass()
    if hasattr(parser, "set_language"):
        parser.set_language(PY_LANG)
    else:
        try:
            parser = ParserClass(PY_LANG)
        except Exception:
            raise RuntimeError("Unable to set tree-sitter language on Parser instance.")
    src_bytes = text.encode("utf8")
    tree = parser.parse(src_bytes)
    root = tree.root_node
    removals: List[EditRange] = []

    def remove_node(n):
        removals.append(EditRange(n.start_byte, n.end_byte))

    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "comment":
            start = node.start_byte
            comment_text = src_bytes[node.start_byte : node.end_byte].decode("utf8", "ignore")
            low = comment_text.lower()
            if start == 0 and comment_text.startswith("#!"):
                pass
            elif "fmt" in low or "type" in low:
                pass
            else:
                remove_node(node)
            continue
        if node.type == "expression_statement":
            if node.child_count >= 1:
                first = node.children[0]
                if first.type in ("string", "string_literal", "string_prefix", "bytes"):
                    is_module_level = node.parent is not None and node.parent.type in ("module", "file_input")
                    if is_module_level:
                        parent = node.parent
                        idx = 0
                        for i, c in enumerate(parent.children):
                            if c is node:
                                idx = i
                                break
                        prev_named = None
                        for prev in reversed(parent.children[:idx]):
                            if getattr(prev, "is_named", True):
                                prev_named = prev
                                break
                        if prev_named is None:
                            if preserve_module_docstring:
                                pass
                            else:
                                remove_node(node)
                        else:
                            remove_node(node)
                    else:
                        remove_node(node)
                    continue
        for c in reversed(node.children):
            stack.append(c)
    if not removals:
        return text
    removals_sorted = sorted(removals, key=lambda r: (r.start, r.end))
    merged: List[EditRange] = []
    cur = removals_sorted[0]
    for r in removals_sorted[1:]:
        if r.start <= cur.end:
            cur.end = max(cur.end, r.end)
        else:
            merged.append(cur)
            cur = r
    merged.append(cur)
    out_bytes = bytearray()
    last = 0
    for r in merged:
        out_bytes.extend(src_bytes[last : r.start])
        last = r.end
    out_bytes.extend(src_bytes[last:])
    return out_bytes.decode("utf8", "ignore")


def ast_tokenize_strip(text: str, preserve_module_docstring: bool = True) -> str:
    module = ast.parse(text)
    docstring_spans: List[Tuple[int, int, int, int]] = []

    def record_docstring(node):
        if not node.body:
            return
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, (ast.Constant, ast.Str))
            and isinstance(getattr(first.value, "value", None), str)
        ):
            lineno = getattr(first, "lineno", None)
            end_lineno = getattr(first, "end_lineno", None)
            col = getattr(first, "col_offset", 0)
            end_col = getattr(first, "end_col_offset", 0)
            if lineno is not None and end_lineno is not None:
                docstring_spans.append((lineno, end_lineno, col, end_col))

    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            record_docstring(node)
    module_docspan = None
    if module.body:
        first = module.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, (ast.Constant, ast.Str))
            and isinstance(getattr(first.value, "value", None), str)
        ):
            lineno = getattr(first, "lineno", None)
            end_lineno = getattr(first, "end_lineno", None)
            col = getattr(first, "col_offset", 0)
            end_col = getattr(first, "end_col_offset", 0)
            if lineno is not None and end_lineno is not None:
                module_docspan = (lineno, end_lineno, col, end_col)
    if preserve_module_docstring and module_docspan is not None:
        docstring_spans = [s for s in docstring_spans if s != module_docspan]
    src_io = io.StringIO(text)
    out_tokens: List[tokenize.TokenInfo] = []
    g = tokenize.generate_tokens(src_io.readline)
    for tok in g:
        tok_type = tok.type
        tok_string = tok.string
        if tok_type == tokenize.COMMENT:
            low = tok_string.lower()
            if tok.start[0] == 1 and tok_string.startswith("#!"):
                out_tokens.append(tok)
            elif "fmt" in low or "type" in low:
                out_tokens.append(tok)
            else:
                pass
        elif tok_type == tokenize.STRING:
            srow, _scol = tok.start
            erow, _ecol = tok.end
            is_doc = False
            for ln, eln, _lc, _ec in docstring_spans:
                if ln == srow and eln == erow:
                    is_doc = True
                    break
            if is_doc:
                pass
            else:
                out_tokens.append(tok)
        else:
            out_tokens.append(tok)
    new_text = tokenize.untokenize(out_tokens)
    return new_text


def process_file_tree_sitter(path: Path, dry_run: bool = False) -> Tuple[bool, Optional[str]]:
    try:
        text, encoding = read_source(path)
    except Exception as e:
        return (False, f"read_error: {e}")
    try:
        new_text = tree_sitter_strip(text, preserve_module_docstring=True)
    except Exception as e:
        return (False, f"parser_error: {e}")
    if new_text == text:
        return (False, None)
    try:
        ast.parse(new_text)
    except Exception as e:
        return (False, f"ast_validation_failed: {e}")
    if not dry_run:
        try:
            write_source(path, new_text, encoding)
        except Exception as e:
            return (False, f"write_error: {e}")
    return (True, None)


def process_file_ast(path: Path, dry_run: bool = True) -> Tuple[bool, Optional[str]]:
    try:
        text, encoding = read_source(path)
    except Exception as e:
        return (False, f"read_error: {e}")
    try:
        new_text = ast_tokenize_strip(text, preserve_module_docstring=True)
    except Exception as e:
        return (False, f"ast_strip_error: {e}")
    if new_text == text:
        return (False, None)
    try:
        ast.parse(new_text)
    except Exception as e:
        return (False, f"ast_validation_failed: {e}")
    if not dry_run:
        try:
            write_source(path, new_text, encoding)
        except Exception as e:
            return (False, f"write_error: {e}")
    return (True, None)


def gather_py_files(root: Path) -> List[Path]:
    files = [p for p in root.rglob("*.py") if p.is_file() and (not should_skip_path(p))]
    return sorted(files)


def run_parallel(paths: Sequence[Path], worker_func, workers: int = None, dry_run: bool = False):
    changed = 0
    errors = []
    start = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(worker_func, p, dry_run): p for p in paths}
        for fut in as_completed(futures):
            p = futures[fut]
            try:
                ok, err = fut.result()
                if ok:
                    changed += 1
                if err:
                    errors.append((p, err))
            except Exception as e:
                errors.append((p, f"exception: {e}"))
    elapsed = time.perf_counter() - start
    return (changed, errors, elapsed)


def main(argv: Optional[List[str]] = None):
    ap = argparse.ArgumentParser(prog="remove_comments_docstrings.py")
    ap.add_argument(
        "--root", "-r", default=".", help="Root directory to search for .py files (default: current directory)."
    )
    ap.add_argument(
        "--workers", "-j", type=int, default=None, help="Number of parallel worker processes (default: cpu count)."
    )
    ap.add_argument("--dry-run", action="store_true", help="Do not write any files. Useful to test before writing.")
    ap.add_argument("--limit", type=int, default=0, help="Limit number of files processed (for quick tests).")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    files = gather_py_files(root)
    if args.limit > 0:
        files = files[: args.limit]
    if not files:
        print("No Python files found.")
        return 0
    print(f"Found {len(files)} Python files under {root}")
    if args.dry_run:
        print("Dry-run requested; not writing files. Files will be analyzed but not updated.")
    print("Processing files with tree-sitter implementation...")
    changed, errors, elapsed = run_parallel(files, process_file_tree_sitter, workers=args.workers, dry_run=args.dry_run)
    print(f"Done: processed {len(files)} files in {elapsed:.3f}s; would update {changed} files; errors: {len(errors)}")
    if errors:
        print("Errors (file, reason):")
        for p, e in errors:
            print(f" - {p}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
