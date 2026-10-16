#!/data/data/com.termux/files/usr/bin/python


from __future__ import annotations

import argparse
import ast
import io
import multiprocessing as mp
import os
import re
import shutil
import subprocess
import sys
import time
import tokenize
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from functools import lru_cache, partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator, NamedTuple, Sequence

from loguru import logger

# --------------------------------------------------------------------------- #
# Optional rich (progress bars).  Falls back silently to plain output.
# --------------------------------------------------------------------------- #
try:
    from rich.console import Console
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    _HAS_RICH = True
except ImportError:  # pragma: no cover
    _HAS_RICH = False

if TYPE_CHECKING:
    import libcst as cst

BACKENDS: tuple[str, ...] = ("ast", "libcst", "tree-sitter")
PYTHON_SUFFIXES: frozenset[str] = frozenset({".py", ".pyw", ".pyi"})
SKIP_DIRS: frozenset[str] = frozenset({
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
})

TYPE_COMMENT_RE = re.compile(r"#\s*type:")
FMT_COMMENT_RE = re.compile(r"#\s*fmt:\s*(?:on|off|skip)\b")
CODING_RE = re.compile(r"#.*?coding[:=]\s*[-\w.]+")
STRING_PREFIX_RE = re.compile(r"[A-Za-z]*")

GREEN = "\033[32m"
RESET = "\033[0m"


def is_preserved_comment(text: str) -> bool:
    """Shebangs, type comments, fmt directives and encoding cookies are preserved by default."""
    return text.startswith("#!") or bool(
        TYPE_COMMENT_RE.match(text) or FMT_COMMENT_RE.match(text) or CODING_RE.match(text)
    )


@dataclass(frozen=True)
class Options:
    backend: str = "ast"
    comments: bool = False
    docstrings: bool = False
    everything: bool = False
    types: bool = False
    clipboard: bool = False

    @property
    def strip_def_docstrings(self) -> bool:
        return self.docstrings or self.everything

    @property
    def strip_module_docstring(self) -> bool:
        return self.everything

    def removes_comment(self, text: str, inline: bool) -> bool:
        if self.everything:
            return True
        if self.types and TYPE_COMMENT_RE.match(text):
            return True
        if is_preserved_comment(text):
            return False
        # BUG FIX: previously `return self.comments or inline`, which removed
        # *every* inline comment even without -c/--comments.  Now comments are
        # only stripped when the user explicitly asked for it.
        return self.comments


class Edit(NamedTuple):
    start: int
    end: int
    replacement: bytes = b""


class StmtSpan(NamedTuple):
    start: int
    end: int
    removable: bool


class FileResult(NamedTuple):
    path: Path
    before: int
    after: int
    output: str | None = None
    skipped: bool = False
    error: str | None = None


# --------------------------------------------------------------------------- #
# Byte-level edit engine
# --------------------------------------------------------------------------- #


def _expand_to_full_line(src: bytes, start: int, end: int) -> tuple[int, int]:
    line_start = src.rfind(b"\n", 0, start) + 1
    line_end = src.find(b"\n", end)
    line_end = len(src) if line_end == -1 else line_end + 1
    if src[line_start:start].strip() or src[end:line_end].strip():
        return start, end
    return line_start, line_end


def apply_edits(src: bytes, edits: Sequence[Edit]) -> bytes:
    spans: list[tuple[int, int, bytes]] = []
    for edit in edits:
        start, end = edit.start, edit.end
        if not edit.replacement:
            start, end = _expand_to_full_line(src, start, end)
        spans.append((start, end, edit.replacement))
    spans.sort()

    parts: list[bytes] = []
    cursor = 0
    for start, end, replacement in spans:
        if start < cursor:
            continue
        parts.append(src[cursor:start])
        parts.append(replacement)
        cursor = end
    parts.append(src[cursor:])
    return b"".join(parts)


def _comment_edit(src: bytes, start: int, end: int, inline: bool) -> Edit:
    if inline:
        while start > 0 and src[start - 1] in b" \t":
            start -= 1
    return Edit(start, end)


def _statement_removal(src: bytes, start: int, end: int) -> Edit:
    j = end
    while j < len(src) and src[j] in b" \t":
        j += 1
    if src[j : j + 1] == b";":
        k = j + 1
        while k < len(src) and src[k] in b" \t":
            k += 1
        return Edit(start, k)
    k = start
    while k > 0 and src[k - 1] in b" \t":
        k -= 1
    if k > 0 and src[k - 1 : k] == b";":
        return Edit(k - 1, end)
    return Edit(start, end)


def _body_edits(src: bytes, stmts: Sequence[StmtSpan], is_module: bool) -> list[Edit]:
    all_removable = bool(stmts) and all(s.removable for s in stmts)
    edits: list[Edit] = []
    for index, stmt in enumerate(stmts):
        if not stmt.removable:
            continue
        if all_removable and index == 0 and not is_module:
            edits.append(Edit(stmt.start, stmt.end, b"pass"))
        else:
            edits.append(_statement_removal(src, stmt.start, stmt.end))
    return edits


def _line_starts(src: bytes) -> list[int]:
    starts = [0]
    pos = src.find(b"\n")
    while pos != -1:
        starts.append(pos + 1)
        pos = src.find(b"\n", pos + 1)
    return starts


# --------------------------------------------------------------------------- #
# ast backend
# --------------------------------------------------------------------------- #


def _ast_comment_edits(text: str, src: bytes, starts: list[int], opts: Options) -> list[Edit]:
    edits: list[Edit] = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type != tokenize.COMMENT:
            continue
        row, col = tok.start
        prefix = tok.line[:col]
        inline = bool(prefix.strip())
        if not opts.removes_comment(tok.string, inline):
            continue
        start = starts[row - 1] + len(prefix.encode("utf-8"))
        end = start + len(tok.string.encode("utf-8"))
        edits.append(_comment_edit(src, start, end, inline))
    return edits


def _ast_removable(stmt: ast.stmt, index: int, owner: ast.AST, opts: Options) -> bool:
    is_docstring = (
        index == 0
        and isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )
    if is_docstring:
        if isinstance(owner, ast.Module):
            return opts.strip_module_docstring
        if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return opts.strip_def_docstrings
        return False
    return opts.types and isinstance(stmt, ast.AnnAssign) and stmt.value is None


def _ast_function_annotations(fn: ast.FunctionDef | ast.AsyncFunctionDef, src: bytes, offset: Any) -> list[Edit]:
    edits: list[Edit] = []
    arguments = fn.args
    params: list[ast.arg] = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    if arguments.vararg is not None:
        params.append(arguments.vararg)
    if arguments.kwarg is not None:
        params.append(arguments.kwarg)

    for arg in params:
        ann = arg.annotation
        if ann is None:
            continue
        name_at = offset(arg.lineno, arg.col_offset)
        ann_at = offset(ann.lineno, ann.col_offset)
        ann_end = offset(ann.end_lineno, ann.end_col_offset)
        colon = src.find(b":", name_at, ann_at)
        if colon == -1:
            continue
        edits.append(Edit(colon, ann_end))

    if fn.returns is not None:
        ret_at = offset(fn.returns.lineno, fn.returns.col_offset)
        ret_end = offset(fn.returns.end_lineno, fn.returns.end_col_offset)
        arrow = src.rfind(b"->", offset(fn.lineno, fn.col_offset), ret_at)
        if arrow == -1:
            return edits
        start = arrow
        while start > 0 and src[start - 1] in b" \t\r\n\f":
            start -= 1
        edits.append(Edit(start, ret_end))
    return edits


def _ast_structure_edits(tree: ast.Module, src: bytes, starts: list[int], opts: Options) -> list[Edit]:
    def offset(line: int, col: int) -> int:
        return starts[line - 1] + col

    def span(node: ast.AST) -> tuple[int, int]:
        return (
            offset(node.lineno, node.col_offset),  # type: ignore[attr-defined]
            offset(node.end_lineno, node.end_col_offset),  # type: ignore[attr-defined]
        )

    edits: list[Edit] = []
    for owner in ast.walk(tree):
        if opts.types:
            if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                edits.extend(_ast_function_annotations(owner, src, offset))
            elif isinstance(owner, ast.AnnAssign) and owner.value is not None:
                ann_start, ann_end = span(owner.annotation)
                target_end = offset(
                    owner.target.end_lineno,  # type: ignore[attr-defined]
                    owner.target.end_col_offset,  # type: ignore[attr-defined]
                )
                colon = src.find(b":", target_end, ann_start)
                if colon != -1:
                    edits.append(Edit(colon, ann_end))

        for field in ("body", "orelse", "finalbody"):
            seq = getattr(owner, field, None)
            if not isinstance(seq, list) or not seq or not isinstance(seq[0], ast.stmt):
                continue
            items = [StmtSpan(*span(stmt), _ast_removable(stmt, i, owner, opts)) for i, stmt in enumerate(seq)]
            edits.extend(_body_edits(src, items, is_module=isinstance(owner, ast.Module)))
    return edits


def _strip_ast(text: str, src: bytes, opts: Options) -> bytes:
    tree = ast.parse(text, type_comments=True)
    starts = _line_starts(src)
    edits = _ast_comment_edits(text, src, starts, opts)
    edits.extend(_ast_structure_edits(tree, src, starts, opts))
    return apply_edits(src, edits)


# --------------------------------------------------------------------------- #
# tree-sitter backend
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def _ts_parser() -> Any:
    try:
        import tree_sitter
        import tree_sitter_python
    except ImportError as exc:
        raise RuntimeError("tree-sitter backend requires: pip install tree-sitter tree-sitter-python") from exc
    return tree_sitter.Parser(tree_sitter.Language(tree_sitter_python.language()))


def _ts_child(node: Any, kind: str) -> Any | None:
    for child in node.children:
        if child.type == kind:
            return child
    return None


def _ts_is_docstring(stmt: Any, src: bytes) -> bool:
    if stmt.type != "expression_statement" or stmt.named_child_count != 1:
        return False
    string = stmt.named_children[0]
    if string.type != "string":
        return False
    raw = src[string.start_byte : string.end_byte].decode("ascii", "replace")
    m = STRING_PREFIX_RE.match(raw)
    prefix = (m.group(0) if m else "").lower()
    return "b" not in prefix and "f" not in prefix


def _ts_removable(stmt: Any, index: int, owner: Any, src: bytes, opts: Options) -> bool:
    if index == 0 and _ts_is_docstring(stmt, src):
        if owner.type == "module":
            return opts.strip_module_docstring
        if owner.type in ("function_definition", "class_definition"):
            return opts.strip_def_docstrings
        return False
    if opts.types and stmt.type == "expression_statement" and stmt.named_child_count == 1:
        child = stmt.named_children[0]
        return (
            child.type == "assignment"
            and child.child_by_field_name("type") is not None
            and child.child_by_field_name("right") is None
        )
    return False


def _ts_annotation_edits(node: Any) -> list[Edit]:
    kind = node.type
    if kind in ("typed_parameter", "typed_default_parameter"):
        colon, ann = _ts_child(node, ":"), node.child_by_field_name("type")
        if colon is not None and ann is not None:
            return [Edit(colon.start_byte, ann.end_byte)]
    elif kind == "function_definition":
        params = node.child_by_field_name("parameters")
        ret = node.child_by_field_name("return_type")
        if params is not None and ret is not None:
            return [Edit(params.end_byte, ret.end_byte)]
    elif kind == "assignment":
        ann = node.child_by_field_name("type")
        right = node.child_by_field_name("right")
        colon = _ts_child(node, ":")
        if ann is not None and right is not None and colon is not None:
            return [Edit(colon.start_byte, ann.end_byte)]
    return []


def _strip_treesitter(src: bytes, opts: Options) -> bytes:
    root = _ts_parser().parse(src).root_node
    if root.has_error:
        raise SyntaxError("tree-sitter reported a parse error")

    edits: list[Edit] = []
    stack: list[Any] = [root]
    while stack:
        node = stack.pop()
        kind = node.type
        if kind == "comment":
            line_start = src.rfind(b"\n", 0, node.start_byte) + 1
            inline = bool(src[line_start : node.start_byte].strip())
            text = src[node.start_byte : node.end_byte].decode("utf-8", "replace")
            if opts.removes_comment(text, inline):
                edits.append(_comment_edit(src, node.start_byte, node.end_byte, inline))
        elif kind in ("module", "block"):
            owner = node if kind == "module" else node.parent
            stmts = [c for c in node.named_children if c.type != "comment"]
            items = [
                StmtSpan(c.start_byte, c.end_byte, _ts_removable(c, i, owner, src, opts)) for i, c in enumerate(stmts)
            ]
            edits.extend(_body_edits(src, items, is_module=kind == "module"))
        elif opts.types:
            edits.extend(_ts_annotation_edits(node))
        stack.extend(node.children)
    return apply_edits(src, edits)


# --------------------------------------------------------------------------- #
# libcst backend
# --------------------------------------------------------------------------- #


def _libcst_stripper(opts: Options) -> cst.CSTTransformer:
    import libcst as cst

    def is_str_literal(node: cst.BaseExpression) -> bool:
        if isinstance(node, cst.ConcatenatedString):
            return is_str_literal(node.left) and is_str_literal(node.right)
        if isinstance(node, cst.SimpleString):
            m = STRING_PREFIX_RE.match(node.value)
            prefix = (m.group(0) if m else "").lower()
            return "b" not in prefix and "f" not in prefix
        return False

    def is_doc_small(node: cst.BaseSmallStatement) -> bool:
        return isinstance(node, cst.Expr) and is_str_literal(node.value)

    def is_doc_line(node: cst.BaseStatement) -> bool:
        return isinstance(node, cst.SimpleStatementLine) and bool(node.body) and is_doc_small(node.body[0])

    def drop_docstring(stmts: list[cst.BaseStatement]) -> list[cst.BaseStatement]:
        first = stmts[0]
        assert isinstance(first, cst.SimpleStatementLine)
        if len(first.body) > 1:
            return [first.with_changes(body=list(first.body[1:])), *stmts[1:]]
        rest = stmts[1:]
        if rest:
            rest[0] = rest[0].with_changes(leading_lines=[*first.leading_lines, *rest[0].leading_lines])
        return rest

    def finish_body(body: Any, drop_doc: bool) -> Any:
        if isinstance(body, cst.IndentedBlock):
            stmts = list(body.body)
            if drop_doc and stmts and is_doc_line(stmts[0]):
                stmts = drop_docstring(stmts)
            return body.with_changes(body=stmts or [cst.SimpleStatementLine(body=[cst.Pass()])])
        if isinstance(body, cst.SimpleStatementSuite):
            smalls = list(body.body)
            if drop_doc and smalls and is_doc_small(smalls[0]):
                smalls = smalls[1:]
            return body.with_changes(body=smalls or [cst.Pass()])
        return body

    class _Stripper(cst.CSTTransformer):
        def leave_EmptyLine(self, original: cst.EmptyLine, updated: cst.EmptyLine) -> Any:
            if updated.comment is not None and opts.removes_comment(updated.comment.value, inline=False):
                return cst.RemovalSentinel.REMOVE
            return updated

        def leave_TrailingWhitespace(self, original: cst.TrailingWhitespace, updated: cst.TrailingWhitespace) -> Any:
            if updated.comment is not None and opts.removes_comment(updated.comment.value, inline=True):
                return updated.with_changes(whitespace=cst.SimpleWhitespace(""), comment=None)
            return updated

        def leave_SimpleStatementLine(self, original: Any, updated: Any) -> Any:
            return updated if updated.body else cst.RemovalSentinel.REMOVE

        def leave_SimpleStatementSuite(self, original: Any, updated: Any) -> Any:
            return updated if updated.body else updated.with_changes(body=[cst.Pass()])

        def leave_IndentedBlock(self, original: Any, updated: Any) -> Any:
            return updated if updated.body else updated.with_changes(body=[cst.SimpleStatementLine(body=[cst.Pass()])])

        def leave_Param(self, original: Any, updated: Any) -> Any:
            if opts.types and updated.annotation is not None:
                return updated.with_changes(annotation=None)
            return updated

        def leave_AnnAssign(self, original: Any, updated: Any) -> Any:
            if not opts.types:
                return updated
            if updated.value is None:
                return cst.RemovalSentinel.REMOVE
            return cst.Assign(
                targets=[cst.AssignTarget(target=updated.target)],
                value=updated.value,
                semicolon=updated.semicolon,
            )

        def leave_FunctionDef(self, original: Any, updated: Any) -> Any:
            body = finish_body(updated.body, opts.strip_def_docstrings)
            if opts.types:
                return updated.with_changes(body=body, returns=None)
            return updated.with_changes(body=body)

        def leave_ClassDef(self, original: Any, updated: Any) -> Any:
            return updated.with_changes(body=finish_body(updated.body, opts.strip_def_docstrings))

        def leave_Module(self, original: Any, updated: Any) -> Any:
            if not opts.strip_module_docstring:
                return updated
            body = list(updated.body)
            if body and is_doc_line(body[0]):
                body = drop_docstring(body)
            return updated.with_changes(body=body)

    return _Stripper()


def _strip_libcst(text: str, opts: Options) -> str:
    try:
        import libcst as cst
    except ImportError as exc:
        raise RuntimeError("libcst backend requires: pip install libcst") from exc
    module = cst.parse_module(text)
    return module.visit(_libcst_stripper(opts)).code


# --------------------------------------------------------------------------- #
# Dispatch / validation / file I/O
# --------------------------------------------------------------------------- #


def strip_source(text: str, opts: Options) -> str:
    if opts.backend == "libcst":
        return _strip_libcst(text, opts)
    src = text.encode("utf-8")
    if opts.backend == "tree-sitter":
        return _strip_treesitter(src, opts).decode("utf-8")
    return _strip_ast(text, src, opts).decode("utf-8")


def _compile(code: str, name: str) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        compile(code, name, "exec", dont_inherit=True)


def _is_python_text(text: str) -> bool:
    first_line = text.split("\n", 1)[0]
    if first_line.startswith("#!") and "python" in first_line:
        return True
    try:
        _compile(text, "<probe>")
    except (SyntaxError, ValueError):
        return False
    return True


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.strip-tmp")
    try:
        tmp.write_bytes(data)
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def process_file(path: Path, opts: Options) -> FileResult:
    """Runs in a worker process (or sequentially).  Never raises -- returns a FileResult."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return FileResult(path, 0, 0, error=f"read failed: {exc}")

    try:
        encoding = tokenize.detect_encoding(io.BytesIO(raw).readline)[0]
        text = raw.decode(encoding)
    except (SyntaxError, LookupError, UnicodeDecodeError) as exc:
        if path.suffix:
            return FileResult(path, len(raw), len(raw), error=f"cannot decode: {exc}")
        return FileResult(path, len(raw), len(raw), skipped=True)

    if not path.suffix and not _is_python_text(text):
        return FileResult(path, len(raw), len(raw), skipped=True)

    try:
        new_text = strip_source(text, opts)
        _compile(new_text, str(path))
        final = new_text.encode(encoding)
        if final.decode(encoding) != new_text:
            raise ValueError("re-encoding changed the source")
    except Exception as exc:
        return FileResult(path, len(raw), len(raw), error=f"{type(exc).__name__}: {exc}")

    if final != raw and not opts.clipboard:
        _atomic_write(path, final)
    return FileResult(
        path,
        len(raw),
        len(final),
        output=new_text if opts.clipboard else None,
    )


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #


def _is_skipped(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    return any(part in SKIP_DIRS for part in rel.parts[:-1])


def discover(inputs: Sequence[str]) -> list[Path]:
    roots = [Path(p) for p in inputs] if inputs else [Path.cwd()]
    seen: set[Path] = set()
    files: list[Path] = []

    def add(path: Path) -> None:
        try:
            key = path.resolve()
        except OSError:
            return
        if key not in seen:
            seen.add(key)
            files.append(path)

    for root in roots:
        if root.is_file():
            add(root)
        elif root.is_dir():
            for path in root.rglob("*"):
                try:
                    if not path.is_file() or _is_skipped(path, root):
                        continue
                except OSError:
                    continue
                if path.suffix in PYTHON_SUFFIXES or not path.suffix:
                    add(path)
        else:
            logger.error(f"Not found: {root}")
    return sorted(files)


def ensure_backend(name: str) -> None:
    if name == "libcst":
        try:
            import libcst  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("libcst backend selected but not installed: pip install libcst") from exc
    elif name == "tree-sitter":
        _ts_parser()


# --------------------------------------------------------------------------- #
# Worker orchestration (safe: sequential by default, opt-in parallel)
# --------------------------------------------------------------------------- #


def iter_results(files: list[Path], opts: Options, workers: int) -> Iterator[FileResult]:
    worker = partial(process_file, opts=opts)

    # Sequential path: safe, deterministic, and immune to fork/thread issues.
    if workers <= 1 or len(files) <= 1:
        for path in files:
            yield worker(path)
        return

    # Parallel path: use `spawn` (safer than fork with threads / loguru / rich).
    try:
        ctx = mp.get_context("spawn")
        executor = ProcessPoolExecutor(max_workers=workers, mp_context=ctx)
    except (OSError, ValueError) as exc:
        logger.warning(f"ProcessPool unavailable ({exc}); falling back to sequential")
        for path in files:
            yield worker(path)
        return

    try:
        with executor:
            futures = {executor.submit(worker, path): path for path in files}
            for fut in as_completed(futures):
                path = futures[fut]
                try:
                    yield fut.result()
                except Exception as exc:  # pragma: no cover -- worker crashed hard
                    yield FileResult(path, 0, 0, error=f"worker crashed: {type(exc).__name__}: {exc}")
    except KeyboardInterrupt:
        logger.warning("Interrupted; cancelling workers")
        executor.shutdown(wait=False, cancel_futures=True)
        raise


# --------------------------------------------------------------------------- #
# Presentation helpers
# --------------------------------------------------------------------------- #


def display(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if abs(size) < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def copy_to_clipboard(parts: list[tuple[Path, str]]) -> None:
    if not parts:
        logger.warning("Nothing to copy to clipboard")
        return
    parts.sort(key=lambda item: str(item[0]))
    if len(parts) == 1:
        payload = parts[0][1]
    else:
        payload = "\n\n".join(f"# --- {display(path)} ---\n{code}" for path, code in parts)
    try:
        subprocess.run(["termux-clipboard-set"], input=payload.encode("utf-8"), check=True)
        logger.info(f"Copied {len(payload.encode('utf-8'))} bytes to clipboard")
    except FileNotFoundError:
        logger.error("termux-clipboard-set not found (install Termux:API)")
    except subprocess.CalledProcessError as exc:
        logger.error(f"termux-clipboard-set failed: {exc}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="strip_py",
        description="Strip comments, docstrings and type annotations from Python files.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="files or directories (default: current directory, recursive)",
    )
    parser.add_argument(
        "-b",
        "--backend",
        choices=BACKENDS,
        default="libcst",
        help="parsing backend (default: libcst)",
    )
    parser.add_argument(
        "-c",
        "--comments",
        action="store_true",
        help="remove all comments except shebang, # type and # fmt",
    )
    parser.add_argument(
        "-d",
        "--docstring",
        action="store_true",
        help="remove all docstrings except the module docstring",
    )
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="remove all comments and docstrings, including preserved ones",
    )
    parser.add_argument("-t", "--type", action="store_true", help="remove type annotations and type comments")
    parser.add_argument(
        "-x",
        "--clipboard",
        action="store_true",
        help="equivalent to -a -t, write nothing, copy output to Termux clipboard",
    )
    parser.add_argument(
        "-j",
        "--workers",
        type=int,
        default=1,
        metavar="N",
        help="parallel worker processes (default: 1 = sequential; try 4 on multi-core)",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="disable the rich progress bar (useful for logs / pipes)",
    )
    return parser


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def main(argv: Sequence[str] | None = None) -> int:
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | {message}",
    )

    args = build_parser().parse_args(argv)
    opts = Options(
        backend=args.backend,
        comments=args.comments,
        docstrings=args.docstring,
        everything=args.all or args.clipboard,
        types=args.type or args.clipboard,
        clipboard=args.clipboard,
    )

    logger.info(
        f"backend={opts.backend} "
        f"comments={opts.comments} docstrings={opts.docstrings} "
        f"types={opts.types} everything={opts.everything} "
        f"workers={args.workers}"
    )

    try:
        ensure_backend(opts.backend)
    except RuntimeError as exc:
        logger.error(str(exc))
        return 2

    use_rich = _HAS_RICH and not args.no_progress
    console = Console() if use_rich else None
    log = console.print if console else (lambda m, **k: print(m, flush=True))

    # ---------------- discovery ----------------
    paths_desc = ", ".join(args.paths) if args.paths else "<cwd>"
    logger.info(f"Scanning: {paths_desc}")
    t0 = time.perf_counter()
    if console and sys.stderr.isatty():
        with console.status("[bold cyan]Discovering Python files...", spinner="dots"):
            files = discover(args.paths)
    else:
        files = discover(args.paths)
    logger.info(f"Discovered {len(files)} candidate file(s) in {time.perf_counter() - t0:.2f}s")

    if not files:
        logger.warning("No Python files found")
        return 0

    # ---------------- processing ----------------
    total_saved = 0
    error_count = 0
    skipped_count = 0
    processed = 0
    clipboard_parts: list[tuple[Path, str]] = []
    start_time = time.perf_counter()

    def handle(result: FileResult) -> None:
        nonlocal total_saved, error_count, skipped_count, processed
        processed += 1
        if result.skipped:
            skipped_count += 1
            return
        if result.error:
            error_count += 1
            if console:
                console.print(f"[red]ERROR[/red] {display(result.path)}: {result.error}")
            else:
                print(f"ERROR {display(result.path)}: {result.error}", flush=True)
            return
        saved = result.before - result.after
        total_saved += saved
        if console:
            console.print(f"{display(result.path)} [green]{saved}[/green]")
        else:
            shown = f"{GREEN}{saved}{RESET}" if sys.stdout.isatty() else str(saved)
            print(f"{display(result.path)} {shown}", flush=True)
        if result.output is not None:
            clipboard_parts.append((result.path, result.output))

    result_iter = iter_results(files, opts, args.workers)

    if console and len(files) > 1:
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        )
        with progress:
            task = progress.add_task("Starting...", total=len(files))
            for result in result_iter:
                handle(result)
                progress.update(
                    task,
                    advance=1,
                    description=f"{processed}/{len(files)}",
                )
    else:
        for result in result_iter:
            handle(result)

    elapsed = time.perf_counter() - start_time

    if opts.clipboard:
        copy_to_clipboard(clipboard_parts)

    # ---------------- summary ----------------
    summary = (
        f"Processed {processed} file(s) in {elapsed:.2f}s -- "
        f"removed {total_saved} bytes ({human_size(total_saved)}), "
        f"skipped {skipped_count}, errors {error_count}"
    )
    if console:
        console.rule("[bold]Summary")
        console.print(summary)
    else:
        print(summary, flush=True)

    return 1 if error_count else 0


if __name__ == "__main__":
    sys.exit(main())
