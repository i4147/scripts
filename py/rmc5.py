#!/data/data/com.termux/files/usr/bin/python
from __future__ import annotations
import argparse
import ast
import io
import os
import shutil
import subprocess
import sys
import tempfile
import tokenize
import zipfile
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path
from typing import Callable, Iterable, Iterator
from loguru import logger

SKIP_DIRS: frozenset[str] = frozenset({
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "lazy",
    ".tox",
})
SKIP_DIR_GLOBS: tuple[str, ...] = ("*.egg-info",)
POOL_WORKERS: int = 8
ENCODINGS: tuple[str, ...] = ("utf-8", "utf-8-sig", "latin-1")
GREEN = "\033[32m"
GRAY = "\033[90m"
RESET = "\033[0m"


@dataclass(slots=True)
class FileResult:
    path: Path
    bytes_removed: int = 0
    comments_removed: int = 0
    docstrings_removed: int = 0
    error: str | None = None
    changed: bool = False
    final_code: str | None = None


@dataclass(frozen=True, slots=True)
class Options:
    strip_comments: bool = True
    strip_docstrings: bool = False
    strip_all: bool = False
    strip_types: bool = False
    backend: str = "ast"
    dry_run: bool = False
    remove_module_docstring: bool = False
    clipboard: bool = False


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("unknown", raw, 0, 1, "no encoding worked")


def is_python_candidate(path: Path) -> bool:
    if path.suffix == ".py":
        return True
    if path.suffix:
        return False
    try:
        with path.open("rb") as fh:
            head = fh.readline(256)
        if head.startswith(b"#!") and b"python" in head:
            return True
        if head.strip():
            return False
        if path.stat().st_size > 2_000_000:
            return False
        ast.parse(read_text(path))
        return True
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return False


def iter_targets(inputs: Iterable[Path]) -> Iterator[Path]:
    for root in inputs:
        if root.is_file():
            if root.suffix == ".whl" or is_python_candidate(root):
                yield root
            continue
        if not root.is_dir():
            logger.error("Path does not exist: {}", root)
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames if d not in SKIP_DIRS and not any(Path(d).match(g) for g in SKIP_DIR_GLOBS)
            ]
            base = Path(dirpath)
            for name in filenames:
                p = base / name
                if p.is_symlink() or not p.exists():
                    continue
                if p.suffix == ".whl" or is_python_candidate(p):
                    yield p


def relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


@dataclass(frozen=True, slots=True)
class Edit:
    start: int
    end: int
    replacement: str
    kind: str


def _line_offsets(source: str) -> list[int]:
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def _pos(offsets: list[int], lineno: int, col: int) -> int:
    return offsets[lineno - 1] + col


def _is_preserved_comment(text: str, lineno: int) -> bool:
    body = text.lstrip("#").strip()
    if lineno == 1 and text.startswith("#!"):
        return True
    if text.startswith("# type:") or text.startswith("#type:"):
        return True
    if text.startswith("# fmt:") or text.startswith("# fmt :") or text.startswith("#fmt:"):
        return True
    return body.startswith(("type:", "fmt:"))


def _is_string_stmt(node: ast.AST) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


def _docstring_edits(source: str, tree: ast.Module, opts: Options) -> list[Edit]:
    offsets = _line_offsets(source)
    edits: list[Edit] = []
    remove_all = opts.strip_all or opts.strip_docstrings

    def handle_body(owner: ast.AST, body: list[ast.stmt], is_module: bool) -> None:
        if not body or not _is_string_stmt(body[0]):
            return
        if is_module and not (opts.strip_all or opts.remove_module_docstring):
            return
        if not remove_all and not is_module:
            return
        if not remove_all and is_module and not opts.remove_module_docstring:
            return
        stmt = body[0]
        start = _pos(offsets, stmt.lineno, stmt.col_offset)
        end = _pos(offsets, stmt.end_lineno or stmt.lineno, stmt.end_col_offset or 0)
        only_stmt = len(body) == 1 and not is_module
        replacement = "pass" if only_stmt else ""
        edits.append(Edit(start, end, replacement, "docstring"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Module):
            handle_body(node, node.body, is_module=True)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            handle_body(node, node.body, is_module=False)
    return edits


def _comment_edits(source: str, opts: Options) -> list[Edit]:
    edits: list[Edit] = []
    lines = source.splitlines(keepends=True)
    offsets = _line_offsets(source)
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError) as exc:
        raise SyntaxError(f"tokenize failed: {exc}") from exc
    for tok in tokens:
        if tok.type != tokenize.COMMENT:
            continue
        lineno, col = tok.start
        text = tok.string
        if _is_preserved_comment(text, lineno) and not opts.strip_all:
            continue
        if not opts.strip_comments and not opts.strip_all:
            continue
        line = lines[lineno - 1]
        start = _pos(offsets, lineno, col)
        end = _pos(offsets, lineno, col + len(text))
        before = line[:col]
        if before.strip() == "":
            edits.append(Edit(_pos(offsets, lineno, 0), _pos(offsets, lineno, len(line.rstrip("\r\n"))), "", "comment"))
        else:
            trimmed_start = _pos(offsets, lineno, len(before.rstrip()))
            edits.append(Edit(trimmed_start, end, "", "comment"))
    return edits


def _type_annotation_edits(source: str, tree: ast.Module) -> list[Edit]:
    offsets = _line_offsets(source)
    edits: list[Edit] = []

    def drop_ann(node: ast.AST) -> None:
        if node is None:
            return
        s = _pos(offsets, node.lineno, node.col_offset)
        e = _pos(offsets, node.end_lineno or node.lineno, node.end_col_offset or 0)
        edits.append(Edit(s, e, "", "annotation"))

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns is not None:
                r_start = _pos(offsets, node.returns.lineno, node.returns.col_offset)
                arrow = source.rfind("->", 0, r_start)
                if arrow != -1:
                    end = _pos(
                        offsets, node.returns.end_lineno or node.returns.lineno, node.returns.end_col_offset or 0
                    )
                    edits.append(Edit(arrow, end, "", "annotation"))
            all_args = (
                node.args.posonlyargs
                + node.args.args
                + node.args.kwonlyargs
                + ([node.args.vararg] if node.args.vararg else [])
                + ([node.args.kwarg] if node.args.kwarg else [])
            )
            for arg in all_args:
                if arg.annotation is not None:
                    colon = source.rfind(":", 0, _pos(offsets, arg.lineno, arg.col_offset) + len(arg.arg) + 1)
                    end = _pos(
                        offsets, arg.annotation.end_lineno or arg.annotation.lineno, arg.annotation.end_col_offset or 0
                    )
                    edits.append(Edit(colon, end, "", "annotation"))
        elif isinstance(node, ast.AnnAssign) and node.simple:
            t_end = _pos(offsets, node.target.end_lineno or node.target.lineno, node.target.end_col_offset or 0)
            a_start = _pos(offsets, node.annotation.lineno, node.annotation.col_offset)
            a_end = _pos(
                offsets, node.annotation.end_lineno or node.annotation.lineno, node.annotation.end_col_offset or 0
            )
            if node.value is not None:
                eq = source.find("=", a_end)
                edits.append(Edit(t_end, eq, " ", "annotation"))
            else:
                edits.append(Edit(t_end, a_end, "", "annotation"))
            _ = a_start
    return edits


def _apply_edits(source: str, edits: list[Edit]) -> str:
    seen: set[tuple[int, int]] = set()
    unique: list[Edit] = []
    for e in sorted(edits, key=lambda x: (x.start, x.end)):
        key = (e.start, e.end)
        if key in seen:
            continue
        seen.add(key)
        unique.append(e)
    out = source
    last_start = len(source) + 1
    for e in sorted(unique, key=lambda x: x.start, reverse=True):
        if e.end > last_start:
            continue
        out = out[: e.start] + e.replacement + out[e.end :]
        last_start = e.start
    return out


@dataclass(frozen=True, slots=True)
class Stripped:
    code: str
    comments_removed: int
    docstrings_removed: int


def _count(edits: list[Edit]) -> tuple[int, int]:
    c = sum(1 for e in edits if e.kind == "comment")
    d = sum(1 for e in edits if e.kind == "docstring")
    return c, d


def backend_ast(source: str, opts: Options) -> Stripped:
    tree = ast.parse(source)
    edits: list[Edit] = []
    if opts.strip_comments or opts.strip_all:
        edits += _comment_edits(source, opts)
    if opts.strip_docstrings or opts.strip_all or opts.remove_module_docstring:
        edits += _docstring_edits(source, tree, opts)
    if opts.strip_types or opts.strip_all and opts.strip_types:
        edits += _type_annotation_edits(source, tree)
    code = _apply_edits(source, edits)
    c, d = _count(edits)
    return Stripped(code, c, d)


def backend_libcst(source: str, opts: Options) -> Stripped:
    import libcst as cst

    class _Stripper(cst.CSTTransformer):
        def __init__(self) -> None:
            super().__init__()
            self.comments = 0
            self.docstrings = 0

        def _maybe_strip_docstring(self, body: cst.BaseSuite, is_module: bool) -> cst.BaseSuite:
            if not isinstance(body, cst.IndentedBlock) or not body.body:
                return body
            first = body.body[0]
            if not (
                isinstance(first, cst.SimpleStatementLine)
                and first.body
                and isinstance(first.body[0], cst.Expr)
                and isinstance(first.body[0].value, (cst.SimpleString, cst.ConcatenatedString))
            ):
                return body
            if is_module and not (opts.strip_all or opts.remove_module_docstring):
                return body
            if not is_module and not (opts.strip_all or opts.strip_docstrings):
                return body
            self.docstrings += 1
            rest = list(body.body[1:])
            if not rest:
                rest = [cst.SimpleStatementLine(body=[cst.Pass()])]
            return body.with_changes(body=rest)

        def leave_Module(self, original: cst.Module, updated: cst.Module) -> cst.Module:
            new_body = self._maybe_strip_docstring(cst.IndentedBlock(body=list(updated.body)), is_module=True)
            return updated.with_changes(body=list(new_body.body))

        def leave_FunctionDef(self, original: cst.FunctionDef, updated: cst.FunctionDef) -> cst.FunctionDef:
            return updated.with_changes(body=self._maybe_strip_docstring(updated.body, is_module=False))

        def leave_ClassDef(self, original: cst.ClassDef, updated: cst.ClassDef) -> cst.ClassDef:
            return updated.with_changes(body=self._maybe_strip_docstring(updated.body, is_module=False))

    module = cst.parse_module(source)
    stripper = _Stripper()
    module = module.visit(stripper)
    code = module.code
    if opts.strip_comments or opts.strip_all:
        edits = _comment_edits(code, opts)
        code = _apply_edits(code, edits)
        stripper.comments = sum(1 for e in edits if e.kind == "comment")
    return Stripped(code, stripper.comments, stripper.docstrings)


def backend_tree_sitter(source: str, opts: Options) -> Stripped:
    import tree_sitter_python as tspy
    from tree_sitter import Language, Parser

    parser = Parser(Language(tspy.language()))
    data = source.encode("utf-8")
    tree = parser.parse(data)
    edits: list[Edit] = []

    def walk(node) -> Iterator:
        stack = [node]
        while stack:
            n = stack.pop()
            yield n
            stack.extend(reversed(n.children))

    for n in walk(tree.root_node):
        if n.type == "comment" and (opts.strip_comments or opts.strip_all):
            text = data[n.start_byte : n.end_byte].decode("utf-8", "replace")
            if _is_preserved_comment(text, n.start_point[0] + 1) and not opts.strip_all:
                continue
            line_start = data.rfind(b"\n", 0, n.start_byte) + 1
            before = data[line_start : n.start_byte]
            s = line_start if before.strip() == b"" else n.start_byte - len(before) + len(before.rstrip())
            edits.append(Edit(s, n.end_byte, "", "comment"))
        if n.type == "expression_statement" and n.children and n.children[0].type == "string":
            parent = n.parent
            is_module = parent is not None and parent.type == "module"
            is_body = (
                parent is not None
                and parent.type == "block"
                and parent.parent is not None
                and parent.parent.type in ("function_definition", "class_definition")
            )
            if is_module and not (opts.strip_all or opts.remove_module_docstring):
                continue
            if is_body and not (opts.strip_all or opts.strip_docstrings):
                continue
            if not (is_module or is_body):
                continue
            only = is_body and parent is not None and parent.named_child_count == 1
            edits.append(Edit(n.start_byte, n.end_byte, "pass" if only else "", "docstring"))
    byte_edits = edits
    out_bytes = bytearray(data)
    for e in sorted(byte_edits, key=lambda x: x.start, reverse=True):
        out_bytes[e.start : e.end] = e.replacement.encode("utf-8")
    code = out_bytes.decode("utf-8")
    c, d = _count(edits)
    return Stripped(code, c, d)


BACKENDS: dict[str, Callable[[str, Options], Stripped]] = {
    "ast": backend_ast,
    "libcst": backend_libcst,
    "tree-sitter": backend_tree_sitter,
}


def resolve_backend(requested: str | None) -> str:
    if requested:
        if requested not in BACKENDS:
            raise SystemExit(f"Unknown backend: {requested}")
        return requested
    try:
        import libcst

        return "libcst"
    except ImportError:
        return "ast"


def check_backend_available(name: str) -> None:
    if name == "libcst":
        try:
            import libcst
        except ImportError as exc:
            raise SystemExit("libcst not installed: pip install libcst") from exc
    elif name == "tree-sitter":
        try:
            import tree_sitter
            import tree_sitter_python
        except ImportError as exc:
            raise SystemExit("tree-sitter not installed: pip install tree-sitter tree-sitter-python") from exc


def process_source(source: str, opts: Options) -> Stripped:
    backend_fn = BACKENDS[opts.backend]
    result = backend_fn(source, opts)
    if opts.strip_types or opts.strip_all:
        pass
    ast.parse(result.code)
    return result


def atomic_write(path: Path, text: str, encoding: str = "utf-8") -> None:
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding=encoding,
            dir=path.parent,
            delete=False,
            prefix=f".{path.name}.",
            suffix=".tmp",
            newline="",
        ) as tmp:
            tmp_name = tmp.name
            tmp.write(text)
            tmp.flush()
            os.fsync(tmp.fileno())
        try:
            shutil.copymode(path, tmp_name)
        except OSError:
            pass
        shutil.move(tmp_name, path)
        tmp_name = None
    finally:
        if tmp_name and os.path.exists(tmp_name):
            os.unlink(tmp_name)


def process_python_file(path: Path, opts: Options) -> FileResult:
    result = FileResult(path=path)
    try:
        original = read_text(path)
    except PermissionError as exc:
        result.error = f"PermissionError: {exc}"
        logger.error("PermissionError reading {}: {}", path, exc)
        return result
    except UnicodeDecodeError as exc:
        result.error = f"UnicodeDecodeError: {exc}"
        logger.error("Encoding error in {}: {}", path, exc)
        return result
    except OSError as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        logger.error("I/O error reading {}: {}", path, exc)
        return result
    try:
        stripped = process_source(original, opts)
    except SyntaxError as exc:
        result.error = f"SyntaxError at line {exc.lineno}: {exc.msg}"
        logger.error(
            "SyntaxError in {} line {}: {}\n{}",
            path,
            exc.lineno,
            exc.msg,
            "".join(__import__("traceback").format_exception(exc)),
        )
        return result
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        logger.opt(exception=exc).error("Failed processing {}", path)
        return result
    result.comments_removed = stripped.comments_removed
    result.docstrings_removed = stripped.docstrings_removed
    new_bytes = len(stripped.code.encode("utf-8"))
    old_bytes = len(original.encode("utf-8"))
    result.bytes_removed = max(0, old_bytes - new_bytes)
    result.changed = stripped.code != original
    if opts.clipboard:
        result.final_code = stripped.code
        return result
    if result.changed and not opts.dry_run:
        try:
            atomic_write(path, stripped.code)
        except PermissionError as exc:
            result.error = f"PermissionError writing: {exc}"
            result.changed = False
            logger.error("PermissionError writing {}: {}", path, exc)
        except OSError as exc:
            result.error = f"{type(exc).__name__} writing: {exc}"
            result.changed = False
            logger.opt(exception=exc).error("Write failed for {}", path)
    return result


def _worker_single(args: tuple[Path, Options]) -> FileResult:
    path, opts = args
    return process_python_file(path, opts)


def process_wheel(path: Path, opts: Options) -> FileResult:
    result = FileResult(path=path)
    tmp_dir = Path(tempfile.mkdtemp(prefix="strip_whl_", dir=path.parent))
    out_tmp = tmp_dir / path.name
    try:
        with zipfile.ZipFile(path) as zin:
            bad = zin.testzip()
            if bad is not None:
                result.error = f"Corrupted wheel member: {bad}"
                return result
            total_removed = c_total = d_total = 0
            changed_any = False
            with zipfile.ZipFile(out_tmp, "w", compression=zipfile.ZIP_DEFLATED) as zout:
                for info in zin.infolist():
                    data = zin.read(info.filename)
                    if info.filename.endswith(".py"):
                        try:
                            text = data.decode("utf-8")
                        except UnicodeDecodeError:
                            text = data.decode("latin-1")
                        try:
                            s = process_source(text, opts)
                            if s.code != text and not opts.dry_run:
                                changed_any = True
                                total_removed += len(text.encode()) - len(s.code.encode())
                                c_total += s.comments_removed
                                d_total += s.docstrings_removed
                                data = s.code.encode("utf-8")
                            elif s.code != text:
                                total_removed += len(text.encode()) - len(s.code.encode())
                                c_total += s.comments_removed
                                d_total += s.docstrings_removed
                        except SyntaxError as exc:
                            logger.error("SyntaxError in {}!{} line {}: {}", path, info.filename, exc.lineno, exc.msg)
                    zout.writestr(info, data)
            result.bytes_removed = max(0, total_removed)
            result.comments_removed = c_total
            result.docstrings_removed = d_total
            result.changed = total_removed != 0
            if changed_any and not opts.dry_run:
                shutil.move(str(out_tmp), path)
            return result
    except zipfile.BadZipFile as exc:
        result.error = f"Invalid wheel archive: {exc}"
        logger.error("Invalid wheel {}: {}", path, exc)
        return result
    except OSError as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        logger.opt(exception=exc).error("Wheel I/O failure {}", path)
        return result
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def report(result: FileResult) -> None:
    rel = relpath(result.path)
    if result.error:
        print(f"{rel}    ERROR: {result.error}")
    elif result.changed:
        print(f"{GREEN}{rel}    {result.bytes_removed}{RESET}")
    else:
        print(f"{GRAY}{rel}    (unchanged){RESET}")


def summarize(results: list[FileResult]) -> None:
    total = len(results)
    changed = sum(1 for r in results if r.changed)
    removed = sum(r.bytes_removed for r in results)
    comments = sum(r.comments_removed for r in results)
    docs = sum(r.docstrings_removed for r in results)
    errors = sum(1 for r in results if r.error)
    print(
        f"\nSummary: {total} files | {changed} changed | {removed} bytes removed | "
        f"{comments} comments | {docs} docstrings | {errors} errors"
    )


def copy_to_clipboard(code: str) -> None:
    try:
        subprocess.run(["termux-clipboard-set"], input=code, text=True, check=True)
    except FileNotFoundError:
        logger.error("termux-clipboard-set not found; install Termux:API")
    except subprocess.CalledProcessError as exc:
        logger.error("termux-clipboard-set failed: {}", exc)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Strip comments and docstrings from Python files.")
    p.add_argument("paths", nargs="*", type=Path, help="Files or directories (default: cwd)")
    p.add_argument("-c", "--comments", action="store_true", help="Remove all comments")
    p.add_argument("-d", "--docstring", action="store_true", help="Remove all docstrings except module docstring.")
    p.add_argument("-a", "--all", action="store_true", help="Remove all comments and docstrings, even preserved ones.")
    p.add_argument("-t", "--type", action="store_true", help="Remove type annotations.")
    p.add_argument("-x", action="store_true", help="Equivalent to -a -t; nothing written, output copied to clipboard.")
    p.add_argument(
        "-b",
        "--backend",
        choices=sorted(BACKENDS),
        default=None,
        help="Backend (default: libcst if installed, else ast).",
    )
    p.add_argument("--dry-run", action="store_true", help="Show changes without writing.")
    p.add_argument("--remove-module-docstring", action="store_true", help="Also strip module-level docstrings.")
    return p


def build_options(ns: argparse.Namespace) -> Options:
    strip_all = ns.all or ns.x
    strip_types = ns.type or ns.x
    default_mode = not (ns.comments or ns.docstring or strip_all)
    return Options(
        strip_comments=ns.comments or default_mode or strip_all,
        strip_docstrings=ns.docstring,
        strip_all=strip_all,
        strip_types=strip_types,
        backend=resolve_backend(ns.backend),
        dry_run=ns.dry_run or ns.x,
        remove_module_docstring=ns.remove_module_docstring,
        clipboard=ns.x,
    )


def main(argv: list[str] | None = None) -> int:
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<level>{level}</level> {message}")
    ns = build_parser().parse_args(argv)
    opts = build_options(ns)
    check_backend_available(opts.backend)
    inputs = ns.paths or [Path.cwd()]
    targets = list(iter_targets(inputs))
    wheels = [t for t in targets if t.suffix == ".whl"]
    pys = [t for t in targets if t.suffix != ".whl"]
    results: list[FileResult] = []
    if pys:
        with Pool(POOL_WORKERS) as pool:
            for res in pool.imap_unordered(_worker_single, [(p, opts) for p in pys]):
                report(res)
                results.append(res)
    for whl in wheels:
        res = process_wheel(whl, opts)
        report(res)
        results.append(res)
    summarize(results)
    if opts.clipboard:
        finals = [r.final_code for r in results if r.final_code is not None]
        if len(finals) == 1:
            copy_to_clipboard(finals[0])
        elif finals:
            copy_to_clipboard("\n".join(finals))
        else:
            logger.warning("No output produced for clipboard")
    return 1 if any(r.error for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
