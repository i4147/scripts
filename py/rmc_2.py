#!/data/data/com.termux/files/usr/bin/python

from __future__ import annotations
import argparse
import ast
import codecs
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import ExitStack, suppress
from dataclasses import dataclass, replace
from functools import cache, partial
import importlib.util
import io
from multiprocessing import Pool
import os
from pathlib import Path, PurePath
import re
import subprocess
import sys
import tempfile
import tokenize
from typing import TYPE_CHECKING
import warnings
import zipfile

from loguru import logger


if TYPE_CHECKING:
    import libcst as cst
    from tree_sitter import Node, Parser
SKIP_DIRS: frozenset[str] = frozenset({
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "lazy",
    "pip",
    "setuptools",
    "numpy",
    "scipy",
    "pandas",
    "packaging",
    "numba",
    ".tox",
})
SKIP_DIR_PATTERNS: tuple[str, ...] = ("*.egg-info",)
MAX_WORKERS: int = 8
MAX_SNIFF_SIZE: int = 2_000_000
DEFAULT_BACKENDS: tuple[str, ...] = ("libcst", "tree-sitter", "ast")
INSTALL_HINTS: dict[str, str] = {
    "libcst": "libcst not installed: pip install libcst",
    "tree-sitter": "tree-sitter not installed: pip install tree-sitter tree-sitter-python",
}
GREEN: str = "\x1b[32m"
GRAY: str = "\x1b[90m"
RESET: str = "\x1b[0m"
NEWLINE_RE: re.Pattern[bytes] = re.compile(rb"\r\n|\r|\n")
SEMICOLON_RE: re.Pattern[bytes] = re.compile(rb"[ \t]*;[ \t]*")
CLOSE_PAREN_RE: re.Pattern[bytes] = re.compile(rb"\s*\)")
STRING_PREFIX_RE: re.Pattern[bytes] = re.compile(rb"[A-Za-z]*")
KEEP_COMMENT_RE: re.Pattern[str] = re.compile(r"#+\s*(?:type:|fmt\s*:)")
CODING_RE: re.Pattern[str] = re.compile(r"#.*?coding[:=]\s*[-\w.]+")
BLOCK_FIELDS: tuple[str, ...] = ("body", "orelse", "finalbody")


@dataclass(frozen=True, slots=True)
class Options:
    strip_comments: bool = True
    strip_docstrings: bool = False
    strip_all: bool = False
    strip_types: bool = False
    backends: tuple[str, ...] = ("ast",)
    dry_run: bool = False
    remove_module_docstring: bool = False
    clipboard: bool = False

    @property
    def drop_comments(self) -> bool:
        return self.strip_comments or self.strip_all

    @property
    def drop_docstrings(self) -> bool:
        return self.strip_docstrings or self.strip_all

    @property
    def drop_module_docstring(self) -> bool:
        return self.strip_all or self.remove_module_docstring


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
class Stripped:
    code: str
    comments: int
    docstrings: int


@dataclass(frozen=True, slots=True)
class Edit:
    start: int
    end: int
    replacement: bytes
    kind: str


type Backend = Callable[[str, Options], Stripped]


def configure_logging() -> None:
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<level>{level}</level> {message}")


def decode_source(raw: bytes) -> tuple[str, str]:
    if raw.startswith(codecs.BOM_UTF8):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("latin-1"), "latin-1"


def parse_tree(text: str) -> ast.Module:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ast.parse(text)


def parses(text: str) -> bool:
    try:
        parse_tree(text)
    except Exception:
        return False
    return True


def line_starts(raw: bytes) -> list[int]:
    return [0, *(match.end() for match in NEWLINE_RE.finditer(raw))]


def node_span(starts: Sequence[int], node: ast.expr | ast.stmt | ast.arg) -> tuple[int, int]:
    end_line = node.end_lineno if node.end_lineno is not None else node.lineno
    end_col = node.end_col_offset if node.end_col_offset is not None else node.col_offset
    return starts[node.lineno - 1] + node.col_offset, starts[end_line - 1] + end_col


def apply_edits(raw: bytes, edits: Iterable[Edit]) -> tuple[bytes, int, int]:
    out = bytearray()
    position = 0
    comments = 0
    docstrings = 0
    for edit in sorted(edits, key=lambda item: (item.start, item.end)):
        if edit.start < position:
            continue
        out += raw[position : edit.start]
        out += edit.replacement
        position = edit.end
        if edit.kind == "comment":
            comments += 1
        elif edit.kind == "docstring":
            docstrings += 1
    out += raw[position:]
    return bytes(out), comments, docstrings


def keep_comment(text: str, lineno: int) -> bool:
    if lineno == 1 and text.startswith("#!"):
        return True
    if lineno <= 2 and CODING_RE.match(text):
        return True
    return KEEP_COMMENT_RE.match(text) is not None


def comment_edit(raw: bytes, line_start: int, comment_start: int, comment_end: int) -> Edit:
    prefix = raw[line_start:comment_start]
    if not prefix.strip():
        return Edit(line_start, comment_end, b"", "comment")
    return Edit(comment_start - (len(prefix) - len(prefix.rstrip())), comment_end, b"", "comment")


def statement_edit(raw: bytes, start: int, end: int, replacement: bytes, kind: str) -> Edit:
    match = SEMICOLON_RE.match(raw, end)
    if match is not None:
        end = match.end()
    return Edit(start, end, replacement, kind)


def block_edits(
    raw: bytes,
    starts: Sequence[int],
    block: Sequence[ast.stmt],
    drop: Sequence[bool],
    is_module: bool,
    kind: str,
) -> list[Edit]:
    if not any(drop):
        return []
    needs_pass = all(drop) and not is_module
    placed = False
    edits: list[Edit] = []
    for statement, flagged in zip(block, drop):
        if not flagged:
            continue
        start, end = node_span(starts, statement)
        replacement = b""
        if needs_pass and not placed:
            replacement = b"pass"
            placed = True
        edits.append(statement_edit(raw, start, end, replacement, kind))
    return edits


def is_docstring_stmt(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def comment_edits(text: str, raw: bytes) -> list[Edit]:
    starts = line_starts(raw)
    lines = io.StringIO(text, newline="").readlines()
    edits: list[Edit] = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(text, newline="").readline):
            if token.type != tokenize.COMMENT:
                continue
            lineno, column = token.start
            yield_edit = token.string
            edits.append(
                (lineno, column, yield_edit)  # type: ignore[arg-type]
            )
    except (tokenize.TokenError, SyntaxError) as exc:
        msg = f"tokenize failed: {exc}"
        raise SyntaxError(msg) from exc
    return [
        comment_edit(
            raw,
            starts[lineno - 1],
            starts[lineno - 1] + len(lines[lineno - 1][:column].encode()),
            starts[lineno - 1] + len(lines[lineno - 1][:column].encode()) + len(string.encode()),
        )
        for lineno, column, string in edits  # type: ignore[misc]
    ]


def strip_comments(text: str, opts: Options) -> tuple[str, int]:
    if not opts.drop_comments:
        return text, 0
    raw = text.encode()
    candidates = comment_edits(text, raw)
    lines = io.StringIO(text, newline="").readlines()
    starts = line_starts(raw)
    kept: list[Edit] = []
    for edit in candidates:
        line_index = max(index for index, value in enumerate(starts) if value <= edit.end - 1 or index == 0)
        del line_index
        kept.append(edit)
    del lines
    filtered: list[Edit] = []
    for edit in kept:
        segment = raw[edit.start : edit.end].decode("utf-8", "replace")
        lineno = raw.count(b"\n", 0, edit.end) + 1
        hash_at = segment.find("#")
        comment_text = segment[hash_at:] if hash_at != -1 else segment
        if not opts.strip_all and keep_comment(comment_text, lineno):
            continue
        filtered.append(edit)
    code, comments, _ = apply_edits(raw, filtered)
    return code.decode(), comments


def strip_docstrings_ast(text: str, opts: Options) -> tuple[str, int]:
    if not (opts.drop_docstrings or opts.drop_module_docstring):
        return text, 0
    raw = text.encode()
    starts = line_starts(raw)
    edits: list[Edit] = []
    for node in ast.walk(parse_tree(text)):
        if isinstance(node, ast.Module):
            allowed = opts.drop_module_docstring
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            allowed = opts.drop_docstrings
        else:
            continue
        if allowed and node.body and is_docstring_stmt(node.body[0]):
            drop = [index == 0 for index in range(len(node.body))]
            edits += block_edits(raw, starts, node.body, drop, isinstance(node, ast.Module), "docstring")
    code, _, docstrings = apply_edits(raw, edits)
    return code.decode(), docstrings


def closing_end(raw: bytes, left: int, annotation_start: int, annotation_end: int) -> int:
    pending = raw.count(b"(", left, annotation_start)
    end = annotation_end
    while pending > 0:
        match = CLOSE_PAREN_RE.match(raw, end)
        if match is None:
            break
        end = match.end()
        pending -= 1
    return end


def function_annotation_edits(
    raw: bytes,
    starts: Sequence[int],
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[Edit]:
    edits: list[Edit] = []
    arguments = node.args
    params: list[ast.arg] = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    if arguments.vararg is not None:
        params.append(arguments.vararg)
    if arguments.kwarg is not None:
        params.append(arguments.kwarg)
    for param in params:
        annotation = param.annotation
        if annotation is None:
            continue
        name_start, _ = node_span(starts, param)
        name_end = name_start + len(param.arg.encode())
        annotation_start, annotation_end = node_span(starts, annotation)
        edits.append(Edit(name_end, closing_end(raw, name_end, annotation_start, annotation_end), b"", "annotation"))
    if node.returns is not None:
        returns_start, returns_end = node_span(starts, node.returns)
        arrow = raw.rfind(b"->", 0, returns_start)
        if arrow != -1:
            begin = arrow
            while begin > 0 and raw[begin - 1 : begin] in (b" ", b"\t"):
                begin -= 1
            edits.append(Edit(begin, closing_end(raw, arrow, returns_start, returns_end), b"", "annotation"))
    return edits


def annotated_assignment_edit(raw: bytes, starts: Sequence[int], node: ast.AnnAssign) -> Edit | None:
    _, target_end = node_span(starts, node.target)
    annotation_start, annotation_end = node_span(starts, node.annotation)
    closed = closing_end(raw, target_end, annotation_start, annotation_end)
    equals = raw.find(b"=", closed)
    if equals == -1:
        return None
    return Edit(target_end, equals, b" ", "annotation")


def strip_annotations(text: str) -> str:
    raw = text.encode()
    starts = line_starts(raw)
    edits: list[Edit] = []
    for node in ast.walk(parse_tree(text)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            edits += function_annotation_edits(raw, starts, node)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            edit = annotated_assignment_edit(raw, starts, node)
            if edit is not None:
                edits.append(edit)
        for field in BLOCK_FIELDS:
            block = getattr(node, field, None)
            if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
                drop = [isinstance(item, ast.AnnAssign) and item.value is None for item in block]
                edits += block_edits(raw, starts, block, drop, isinstance(node, ast.Module), "annotation")
    code, _, _ = apply_edits(raw, edits)
    return code.decode()


def strip_ast(text: str, opts: Options) -> Stripped:
    code, docstrings = strip_docstrings_ast(text, opts)
    code, comments = strip_comments(code, opts)
    return Stripped(code, comments, docstrings)


@cache
def libcst_remover() -> type[cst.CSTTransformer]:
    import libcst as cst

    def is_docstring(node: cst.BaseSmallStatement) -> bool:
        if not isinstance(node, cst.Expr):
            return False
        value = node.value
        if isinstance(value, (cst.SimpleString, cst.ConcatenatedString)):
            return isinstance(value.evaluated_value, str)
        return False

    class Remover(cst.CSTTransformer):
        def __init__(self, drop_module: bool, drop_other: bool) -> None:
            super().__init__()
            self.drop_module = drop_module
            self.drop_other = drop_other
            self.removed = 0

        def strip_lines(self, body: Sequence[cst.BaseStatement], keep_empty: bool) -> list[cst.BaseStatement]:
            first = body[0] if body else None
            if not isinstance(first, cst.SimpleStatementLine) or not first.body or not is_docstring(first.body[0]):
                return list(body)
            self.removed += 1
            if len(first.body) > 1:
                return [first.with_changes(body=list(first.body[1:])), *body[1:]]
            if len(body) > 1 or keep_empty:
                return list(body[1:])
            return [first.with_changes(body=[cst.Pass()])]

        def strip_suite(self, suite: cst.BaseSuite) -> cst.BaseSuite:
            if isinstance(suite, cst.IndentedBlock):
                return suite.with_changes(body=self.strip_lines(suite.body, False))
            small = suite.body
            if small and is_docstring(small[0]):
                self.removed += 1
                return suite.with_changes(body=list(small[1:]) or [cst.Pass()])
            return suite

        def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
            if not self.drop_module:
                return updated_node
            return updated_node.with_changes(body=self.strip_lines(updated_node.body, True))

        def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
            if not self.drop_other:
                return updated_node
            return updated_node.with_changes(body=self.strip_suite(updated_node.body))

        def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
            if not self.drop_other:
                return updated_node
            return updated_node.with_changes(body=self.strip_suite(updated_node.body))

    return Remover


def strip_libcst(text: str, opts: Options) -> Stripped:
    import libcst as cst

    remover = libcst_remover()(opts.drop_module_docstring, opts.drop_docstrings)
    code = cst.parse_module(text).visit(remover).code
    code, comments = strip_comments(code, opts)
    return Stripped(code, comments, remover.removed)


@cache
def tree_sitter_parser() -> Parser:
    from tree_sitter import Language, Parser
    import tree_sitter_python

    return Parser(Language(tree_sitter_python.language()))


def is_plain_string(node: Node, raw: bytes) -> bool:
    if node.type == "string":
        head = raw[node.start_byte : node.end_byte]
        prefix = STRING_PREFIX_RE.match(head)
        letters = prefix.group(0).lower() if prefix else b""
        return not any(letter in b"bft" for letter in letters)
    if node.type == "concatenated_string":
        parts = node.named_children
        return bool(parts) and all(part.type == "string" and is_plain_string(part, raw) for part in parts)
    return False


def tree_sitter_docstring(node: Node, raw: bytes, opts: Options) -> Edit | None:
    parent = node.parent
    if parent is None:
        return None
    if parent.type == "module":
        is_module = True
    elif (
        parent.type == "block"
        and parent.parent is not None
        and parent.parent.type in ("function_definition", "class_definition")
    ):
        is_module = False
    else:
        return None
    if is_module and not opts.drop_module_docstring:
        return None
    if not is_module and not opts.drop_docstrings:
        return None
    siblings = [child for child in parent.named_children if child.type != "comment"]
    if not siblings or siblings[0] != node:
        return None
    if len(node.named_children) != 1 or not is_plain_string(node.named_children[0], raw):
        return None
    replacement = b"pass" if (not is_module and len(siblings) == 1) else b""
    return statement_edit(raw, node.start_byte, node.end_byte, replacement, "docstring")


def strip_tree_sitter(text: str, opts: Options) -> Stripped:
    raw = text.encode()
    tree = tree_sitter_parser().parse(raw)
    edits: list[Edit] = []
    stack: list[Node] = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "comment" and opts.drop_comments:
            end = node.end_byte
            while end > node.start_byte and raw[end - 1] in (10, 13):
                end -= 1
            comment_text = raw[node.start_byte : end].decode("utf-8", "replace")
            if opts.strip_all or not keep_comment(comment_text, node.start_point[0] + 1):
                line_start = raw.rfind(b"\n", 0, node.start_byte) + 1
                edits.append(comment_edit(raw, line_start, node.start_byte, end))
        elif node.type == "expression_statement":
            edit = tree_sitter_docstring(node, raw, opts)
            if edit is not None:
                edits.append(edit)
        stack.extend(node.children)
    code, comments, docstrings = apply_edits(raw, edits)
    return Stripped(code.decode(), comments, docstrings)


BACKENDS: dict[str, Backend] = {
    "libcst": strip_libcst,
    "tree-sitter": strip_tree_sitter,
    "ast": strip_ast,
}


def backend_available(name: str) -> bool:
    if name == "ast":
        return True
    if name == "libcst":
        return importlib.util.find_spec("libcst") is not None
    if name == "tree-sitter":
        return all(importlib.util.find_spec(module) is not None for module in ("tree_sitter", "tree_sitter_python"))
    return False


def resolve_backends(requested: str | None) -> tuple[str, ...]:
    if requested is not None and not backend_available(requested):
        raise SystemExit(INSTALL_HINTS.get(requested, f"Unknown backend: {requested}"))
    order: list[str] = [requested] if requested else []
    order += [name for name in DEFAULT_BACKENDS if name not in order and backend_available(name)]
    return tuple(order)


def strip_source(text: str, opts: Options) -> Stripped:
    source_valid = parses(text)
    errors: list[Exception] = []
    for name in opts.backends:
        try:
            result = BACKENDS[name](text, opts)
            if opts.strip_types:
                result = replace(result, code=strip_annotations(result.code))
            if source_valid:
                parse_tree(result.code)
            return result
        except Exception as exc:
            logger.debug("backend {} failed: {}", name, exc)
            errors.append(exc)
    syntax_error = next((error for error in errors if isinstance(error, SyntaxError)), None)
    if syntax_error is not None:
        raise syntax_error
    raise errors[-1] if errors else RuntimeError("no backend available")


def write_atomic(path: Path, data: bytes) -> None:
    target = path.resolve()
    descriptor, name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        with suppress(OSError):
            temporary.chmod(target.stat().st_mode & 0o7777)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def process_file(path: Path, opts: Options) -> FileResult:
    result = FileResult(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        logger.error("I/O error reading {}: {}", path, exc)
        return result
    text, encoding = decode_source(raw)
    try:
        stripped = strip_source(text, opts)
    except SyntaxError as exc:
        result.error = f"SyntaxError at line {exc.lineno}: {exc.msg}"
        logger.error("SyntaxError in {} line {}: {}", path, exc.lineno, exc.msg)
        return result
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        logger.opt(exception=exc).error("Failed processing {}", path)
        return result
    updated = stripped.code.encode(encoding)
    result.comments_removed = stripped.comments
    result.docstrings_removed = stripped.docstrings
    result.bytes_removed = max(0, len(raw) - len(updated))
    result.changed = updated != raw
    if opts.clipboard:
        result.final_code = stripped.code
        return result
    if result.changed and not opts.dry_run:
        try:
            write_atomic(path, updated)
        except OSError as exc:
            result.error = f"{type(exc).__name__} writing: {exc}"
            result.changed = False
            logger.opt(exception=exc).error("Write failed for {}", path)
    return result


def process_wheel(path: Path, opts: Options) -> FileResult:
    result = FileResult(path)
    try:
        with tempfile.TemporaryDirectory(prefix="strip_whl_", dir=path.parent) as directory:
            staged = Path(directory) / path.name
            removed = comments = docstrings = 0
            modified = False
            with ExitStack() as stack:
                source = stack.enter_context(zipfile.ZipFile(path))
                broken = source.testzip()
                if broken is not None:
                    result.error = f"Corrupted wheel member: {broken}"
                    return result
                target = (
                    None
                    if opts.dry_run
                    else stack.enter_context(zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_DEFLATED))
                )
                for info in source.infolist():
                    data = source.read(info.filename)
                    if info.filename.endswith(".py"):
                        text, encoding = decode_source(data)
                        try:
                            stripped = strip_source(text, opts)
                        except Exception as exc:
                            logger.error("{} in {}!{}: {}", type(exc).__name__, path, info.filename, exc)
                        else:
                            updated = stripped.code.encode(encoding)
                            if updated != data:
                                removed += len(data) - len(updated)
                                comments += stripped.comments
                                docstrings += stripped.docstrings
                                modified = True
                                data = updated
                    if target is not None:
                        target.writestr(info, data)
            result.bytes_removed = max(0, removed)
            result.comments_removed = comments
            result.docstrings_removed = docstrings
            result.changed = modified
            if modified and not opts.dry_run:
                with suppress(OSError):
                    staged.chmod(path.stat().st_mode & 0o7777)
                staged.replace(path)
    except zipfile.BadZipFile as exc:
        result.error = f"Invalid wheel archive: {exc}"
        logger.error("Invalid wheel {}: {}", path, exc)
    except OSError as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        logger.opt(exception=exc).error("Wheel I/O failure {}", path)
    return result


def is_python_file(path: Path) -> bool:
    suffix = path.suffix
    if suffix == ".py":
        return True
    if suffix:
        return False
    try:
        with path.open("rb") as handle:
            first = handle.readline(256)
        if first.startswith(b"#!") and b"python" in first:
            return True
        if first.strip():
            return False
        if path.stat().st_size > MAX_SNIFF_SIZE:
            return False
        parse_tree(decode_source(path.read_bytes())[0])
        return True
    except (OSError, SyntaxError, ValueError, RecursionError, MemoryError):
        return False


def is_candidate(path: Path) -> bool:
    return path.suffix == ".whl" or is_python_file(path)


def walk_directory(root: Path) -> Iterator[Path]:
    for current, directories, files in root.walk():
        directories[:] = [
            name
            for name in directories
            if name not in SKIP_DIRS and not any(PurePath(name).match(pattern) for pattern in SKIP_DIR_PATTERNS)
        ]
        for name in files:
            candidate = current / name
            if candidate.is_symlink() or not candidate.exists():
                continue
            if is_candidate(candidate):
                yield candidate


def discover(roots: Iterable[Path]) -> Iterator[Path]:
    seen: set[Path] = set()
    for root in roots:
        if root.is_file():
            found: Iterator[Path] = iter((root,)) if is_candidate(root) else iter(())
        elif root.is_dir():
            found = walk_directory(root)
        else:
            logger.error("Path does not exist: {}", root)
            continue
        for path in found:
            key = path.resolve()
            if key in seen:
                continue
            seen.add(key)
            yield path


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def report(result: FileResult) -> None:
    name = display_path(result.path)
    if result.error:
        print(f"{name}    ERROR: {result.error}")
    elif result.changed:
        print(f"{GREEN}{name}    {result.bytes_removed}{RESET}")
    else:
        print(f"{GRAY}{name}    (unchanged){RESET}")


def summarize(results: Sequence[FileResult]) -> None:
    changed = sum(1 for item in results if item.changed)
    removed = sum(item.bytes_removed for item in results)
    comments = sum(item.comments_removed for item in results)
    docstrings = sum(item.docstrings_removed for item in results)
    errors = sum(1 for item in results if item.error)
    print(
        f"\nSummary: {len(results)} files | {changed} changed | {removed} bytes removed "
        f"| {comments} comments | {docstrings} docstrings | {errors} errors"
    )


def copy_to_clipboard(code: str) -> None:
    try:
        subprocess.run(["termux-clipboard-set"], input=code, text=True, check=True)
    except FileNotFoundError:
        logger.error("termux-clipboard-set not found; install Termux:API")
    except subprocess.CalledProcessError as exc:
        logger.error("termux-clipboard-set failed: {}", exc)


def run_sources(paths: Sequence[Path], opts: Options) -> Iterator[FileResult]:
    if not paths:
        return
    workers = min(MAX_WORKERS, os.process_cpu_count() or 1, len(paths))
    worker = partial(process_file, opts=opts)
    if workers <= 1:
        yield from map(worker, paths)
        return
    with Pool(workers, initializer=configure_logging) as pool:
        yield from pool.imap_unordered(worker, paths)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strip comments and docstrings from Python files.")
    parser.add_argument("paths", nargs="*", type=Path, help="Files or directories (default: cwd)")
    parser.add_argument("-c", "--comments", action="store_true", help="Remove all comments")
    parser.add_argument("-d", "--docstring", action="store_true", help="Remove all docstrings except module docstring.")
    parser.add_argument(
        "-a", "--all", action="store_true", help="Remove all comments and docstrings, even preserved ones."
    )
    parser.add_argument("-t", "--type", action="store_true", help="Remove type annotations.")
    parser.add_argument(
        "-x", action="store_true", help="Equivalent to -a -t; nothing written, output copied to clipboard."
    )
    parser.add_argument(
        "-b",
        "--backend",
        choices=sorted(BACKENDS),
        default=None,
        help="Preferred backend; others are used as fallback (default order: libcst, tree-sitter, ast).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing.")
    parser.add_argument("--remove-module-docstring", action="store_true", help="Also strip module-level docstrings.")
    return parser


def make_options(args: argparse.Namespace) -> Options:
    strip_all: bool = args.all or args.x
    strip_types: bool = args.type or args.x
    default_comments = not (args.comments or args.docstring or strip_all)
    return Options(
        strip_comments=args.comments or default_comments or strip_all,
        strip_docstrings=args.docstring,
        strip_all=strip_all,
        strip_types=strip_types,
        backends=resolve_backends(args.backend),
        dry_run=args.dry_run or args.x,
        remove_module_docstring=args.remove_module_docstring,
        clipboard=args.x,
    )


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    opts = make_options(args)
    roots: list[Path] = args.paths or [Path.cwd()]
    candidates = list(discover(roots))
    wheels = [path for path in candidates if path.suffix == ".whl"]
    sources = [path for path in candidates if path.suffix != ".whl"]
    results: list[FileResult] = []
    for result in run_sources(sources, opts):
        report(result)
        results.append(result)
    for wheel in wheels:
        result = process_wheel(wheel, opts)
        report(result)
        results.append(result)
    summarize(results)
    if opts.clipboard:
        outputs = [item.final_code for item in results if item.final_code is not None]
        if len(outputs) == 1:
            copy_to_clipboard(outputs[0])
        elif outputs:
            copy_to_clipboard("\n".join(outputs))
        else:
            logger.warning("No output produced for clipboard")
    return 1 if any(item.error for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
