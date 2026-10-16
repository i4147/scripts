#!/data/data/com.termux/files/usr/bin/python3.12

from __future__ import annotations

import argparse
import ast
import codecs
import difflib
import fnmatch
import io
import multiprocessing
import os
import re
import shutil
import signal
import sys
import tempfile
import textwrap
import tokenize
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final, Literal, TypeVar, get_args

import libcst as cst
from libcst.helpers import get_full_name_for_node
from loguru import logger
from tqdm import tqdm

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

WORKERS: Final[int] = 8
TARGET_VERSION: Final[tuple[int, int]] = (3, 12)
PYTHON_SUFFIXES: Final[frozenset[str]] = frozenset({".py", ".pyw"})
IGNORE_FILENAME: Final[str] = ".ignore"
TYPING_MODULES: Final[frozenset[str]] = frozenset({"typing", "typing_extensions"})
MIN_CODE_BLOCK_LINES: Final[int] = 2
DEFAULT_IGNORES: Final[tuple[str, ...]] = (
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    ".tox",
    ".nox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "site-packages",
    "*.egg-info",
)
# Comments that are kept unless --all is given: shebangs, "# type:", "# fmt:".
PROTECTED_COMMENT: Final[re.Pattern[str]] = re.compile(r"^#(?:!|\s*(?:type|fmt):)")
# Attributes of LibCST nodes that hold sequences of EmptyLine (full-line comments).
LINE_FIELDS: Final[tuple[str, ...]] = (
    "leading_lines",
    "lines_after_decorators",
    "footer",
    "header",
    "empty_lines",
)

PoolMethod = Literal["map", "imap", "imap_unordered", "apply", "apply_async"]
POOL_METHODS: Final[tuple[str, ...]] = get_args(PoolMethod)
Status = Literal["changed", "unchanged", "error"]

NodeT = TypeVar("NodeT", bound=cst.CSTNode)
DefT = TypeVar("DefT", cst.FunctionDef, cst.ClassDef)


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CleanerConfig:
    """Which transformations the cleaner applies."""

    strip_block_comments: bool
    strip_docstrings: bool
    strip_type_hints: bool
    preserve_special_comments: bool
    detect_commented_code: bool

    @classmethod
    def from_flags(cls, *, comments: bool, docstrings: bool, type_hints: bool, everything: bool) -> CleanerConfig:
        """Build a config from CLI flags; ``everything`` overrides all safeguards."""
        if everything:
            return cls(True, True, True, False, False)
        return cls(comments, docstrings, type_hints, True, True)


@dataclass(frozen=True, slots=True)
class RunOptions:
    """Per-run I/O behaviour."""

    backup: bool
    dry_run: bool
    want_diff: bool


@dataclass(frozen=True, slots=True)
class FileResult:
    """Outcome of processing one file (returned from worker to parent)."""

    path: str
    status: Status
    comments_removed: int = 0
    docstrings_removed: int = 0
    hints_removed: int = 0
    bytes_saved: int = 0
    message: str = ""
    diff: str = ""


# --------------------------------------------------------------------------- #
# Commented-out-code heuristic
# --------------------------------------------------------------------------- #


def _is_trivial_statement(stmt: ast.stmt) -> bool:
    """True for statements that prose commonly parses as (``word``, ``Note: x``)."""
    if isinstance(stmt, ast.Expr):
        return isinstance(stmt.value, (ast.Name, ast.Constant, ast.Attribute))
    return isinstance(stmt, ast.AnnAssign) and stmt.value is None


def looks_like_code(comment_lines: Sequence[str]) -> bool:
    """Return True if a block of ``#`` lines parses as real Python code.

    The leading ``#`` (and one optional space) is removed from every line, the
    block is dedented and handed to ``ast.parse``.  Blocks shorter than
    ``MIN_CODE_BLOCK_LINES`` and blocks that only parse as bare names or
    constants (typical prose) are rejected to reduce false positives.
    """
    if len(comment_lines) < MIN_CODE_BLOCK_LINES:
        return False
    bodies: list[str] = []
    for raw in comment_lines:
        body = raw[1:]
        bodies.append(body[1:] if body.startswith(" ") else body)
    try:
        tree = ast.parse(textwrap.dedent("\n".join(bodies)), feature_version=TARGET_VERSION)
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return False
    return any(not _is_trivial_statement(stmt) for stmt in tree.body)


# --------------------------------------------------------------------------- #
# LibCST transformers
# --------------------------------------------------------------------------- #


class _BodyRepairMixin(cst.CSTTransformer):
    """Keeps syntax valid when removals leave a block without statements.

    ``leave_IndentedBlock`` and ``leave_SimpleStatementSuite`` substitute a
    ``pass`` statement when every child was removed, so ``def f():`` blocks
    never become empty.
    """

    def leave_IndentedBlock(self, original_node: cst.IndentedBlock, updated_node: cst.IndentedBlock) -> cst.BaseSuite:
        if updated_node.body:
            return updated_node
        return updated_node.with_changes(body=[cst.SimpleStatementLine(body=[cst.Pass()])])

    def leave_SimpleStatementSuite(
        self, original_node: cst.SimpleStatementSuite, updated_node: cst.SimpleStatementSuite
    ) -> cst.BaseSuite:
        if updated_node.body:
            return updated_node
        return updated_node.with_changes(body=[cst.Pass()])


class SourceCleaner(_BodyRepairMixin):
    """Removes comments, docstrings and annotations according to a config.

    Handlers, by LibCST node type:

    * ``TrailingWhitespace``  -- inline comments (always removed unless protected).
    * ``on_leave`` (generic)  -- full-line comment blocks stored in ``EmptyLine``
      sequences; applies the commented-out-code heuristic and protection rules.
    * ``Module`` / ``FunctionDef`` / ``ClassDef`` -- docstrings, replaced by
      ``pass`` when they are a body's only statement; ``FunctionDef`` also drops
      return annotations.
    * ``Param``               -- parameter annotations.
    * ``AnnAssign``           -- ``x: int = 1`` becomes ``x = 1``; bare ``x: int``
      statements are deleted by ``leave_SimpleStatementLine``.

    Counters (``comments_removed`` etc.) feed the ``--stats`` report.
    """

    def __init__(self, config: CleanerConfig) -> None:
        super().__init__()
        self.config = config
        self.comments_removed = 0
        self.docstrings_removed = 0
        self.hints_removed = 0

    # -- comments ---------------------------------------------------------- #

    def _is_protected(self, text: str) -> bool:
        return self.config.preserve_special_comments and PROTECTED_COMMENT.match(text) is not None

    def leave_TrailingWhitespace(
        self, original_node: cst.TrailingWhitespace, updated_node: cst.TrailingWhitespace
    ) -> cst.TrailingWhitespace:
        """Drop an inline comment together with the padding before it."""
        comment = updated_node.comment
        if comment is None or self._is_protected(comment.value):
            return updated_node
        self.comments_removed += 1
        return updated_node.with_changes(whitespace=cst.SimpleWhitespace(""), comment=None)

    def _filter_lines(self, lines: Sequence[cst.EmptyLine]) -> list[cst.EmptyLine]:
        """Filter a sequence of lines, deciding per block of consecutive comments."""
        kept: list[cst.EmptyLine] = []
        block: list[cst.EmptyLine] = []
        for line in [*lines, None]:  # None is a flush sentinel
            if line is not None and line.comment is not None:
                block.append(line)
                continue
            if block:
                texts = [entry.comment.value for entry in block if entry.comment]
                if self.config.detect_commented_code and looks_like_code(texts):
                    kept.extend(block)
                else:
                    for entry in block:
                        if entry.comment and self._is_protected(entry.comment.value):
                            kept.append(entry)
                        else:
                            self.comments_removed += 1
                block = []
            if line is not None:
                kept.append(line)
        return kept

    def on_leave(  # type: ignore[override]
        self, original_node: NodeT, updated_node: NodeT
    ) -> NodeT | cst.RemovalSentinel | cst.FlattenSentinel[NodeT]:
        """Run the specific ``leave_*`` handler, then clean full-line comments."""
        result = super().on_leave(original_node, updated_node)
        if self.config.strip_block_comments and isinstance(result, cst.CSTNode):
            changes: dict[str, list[cst.EmptyLine]] = {}
            for name in LINE_FIELDS:
                value = getattr(result, name, None)
                if isinstance(value, Sequence) and value and isinstance(value[0], cst.EmptyLine):
                    filtered = self._filter_lines(value)
                    if len(filtered) != len(value):
                        changes[name] = filtered
            if changes:
                return result.with_changes(**changes)  # type: ignore[return-value]
        return result

    # -- docstrings -------------------------------------------------------- #

    @staticmethod
    def _is_docstring_expr(stmt: cst.BaseSmallStatement) -> bool:
        """A bare (non-f, non-bytes) string expression statement."""
        if not isinstance(stmt, cst.Expr):
            return False
        value = stmt.value
        if not isinstance(value, (cst.SimpleString, cst.ConcatenatedString)):
            return False
        return isinstance(value.evaluated_value, str)

    def _remove_first_docstring(
        self, body: Sequence[cst.BaseStatement], *, pass_if_empty: bool
    ) -> list[cst.BaseStatement]:
        """Drop a leading docstring statement, keeping any comments above it."""
        if not body:
            return list(body)
        first = body[0]
        if (
            not isinstance(first, cst.SimpleStatementLine)
            or not first.body
            or not self._is_docstring_expr(first.body[0])
        ):
            return list(body)
        self.docstrings_removed += 1
        if len(first.body) > 1:  # '"doc"; x = 1' keeps the rest of the line
            return [first.with_changes(body=first.body[1:]), *body[1:]]
        rest = list(body[1:])
        carried = [line for line in first.leading_lines if line.comment is not None]
        if rest and carried:
            nxt = rest[0]
            if isinstance(nxt, (cst.SimpleStatementLine, cst.BaseCompoundStatement)):
                rest[0] = nxt.with_changes(leading_lines=[*carried, *nxt.leading_lines])
        elif not rest and pass_if_empty:
            rest = [cst.SimpleStatementLine(body=[cst.Pass()], leading_lines=carried)]
        return rest

    def _strip_def_docstring(self, node: DefT) -> DefT:
        body = node.body
        if isinstance(body, cst.IndentedBlock):
            new_body = self._remove_first_docstring(body.body, pass_if_empty=True)
            return node.with_changes(body=body.with_changes(body=new_body))
        if body.body and self._is_docstring_expr(body.body[0]):
            self.docstrings_removed += 1
            rest = list(body.body[1:]) or [cst.Pass()]
            return node.with_changes(body=body.with_changes(body=rest))
        return node

    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
        """Remove the module docstring (an empty module body is valid)."""
        if not self.config.strip_docstrings:
            return updated_node
        body = self._remove_first_docstring(updated_node.body, pass_if_empty=False)
        return updated_node.with_changes(body=body)

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.BaseStatement:
        """Remove a class docstring, substituting ``pass`` if it was the only statement."""
        if self.config.strip_docstrings:
            return self._strip_def_docstring(updated_node)
        return updated_node

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.BaseStatement:
        """Remove the return annotation and/or docstring of a function."""
        node = updated_node
        if self.config.strip_type_hints and node.returns is not None:
            self.hints_removed += 1
            node = node.with_changes(returns=None)
        if self.config.strip_docstrings:
            node = self._strip_def_docstring(node)
        return node

    # -- type hints -------------------------------------------------------- #

    def leave_Param(self, original_node: cst.Param, updated_node: cst.Param) -> cst.Param:
        """Remove ``: annotation`` from a parameter (including ``*args``/``**kw``)."""
        if self.config.strip_type_hints and updated_node.annotation is not None:
            self.hints_removed += 1
            return updated_node.with_changes(annotation=None)
        return updated_node

    def leave_AnnAssign(self, original_node: cst.AnnAssign, updated_node: cst.AnnAssign) -> cst.BaseSmallStatement:
        """``x: int = 1`` -> ``x = 1``.  Valueless ones are removed by the line handler."""
        if not self.config.strip_type_hints or updated_node.value is None:
            return updated_node
        self.hints_removed += 1
        return cst.Assign(
            targets=[cst.AssignTarget(target=updated_node.target)],
            value=updated_node.value,
            semicolon=updated_node.semicolon,
        )

    def leave_SimpleStatementLine(
        self, original_node: cst.SimpleStatementLine, updated_node: cst.SimpleStatementLine
    ) -> cst.BaseStatement | cst.RemovalSentinel:
        """Delete bare annotations (``x: int``) and lines left empty."""
        if self.config.strip_type_hints:
            kept = [stmt for stmt in updated_node.body if not (isinstance(stmt, cst.AnnAssign) and stmt.value is None)]
            if len(kept) != len(updated_node.body):
                self.hints_removed += len(updated_node.body) - len(kept)
                if not kept:
                    return cst.RemoveFromParent()
                return updated_node.with_changes(body=kept)
        return updated_node


class _NameCollector(cst.CSTVisitor):
    """Collects every identifier used outside import statements."""

    def __init__(self) -> None:
        super().__init__()
        self.used: set[str] = set()

    def visit_Name(self, node: cst.Name) -> bool:
        self.used.add(node.value)
        return False

    def visit_Import(self, node: cst.Import) -> bool:
        return False

    def visit_ImportFrom(self, node: cst.ImportFrom) -> bool:
        return False


class _UnusedTypingImportRemover(_BodyRepairMixin):
    """Removes ``typing`` / ``typing_extensions`` imports whose names are unused.

    Works from the set of names found by ``_NameCollector`` (a conservative
    approximation of scope analysis: any remaining use anywhere keeps the
    import).  ``from typing import *`` is never touched.
    """

    def __init__(self, used: frozenset[str]) -> None:
        super().__init__()
        self.used = used

    @staticmethod
    def _bound_name(alias: cst.ImportAlias) -> str:
        if alias.asname is not None and isinstance(alias.asname.name, cst.Name):
            return alias.asname.name.value
        return get_full_name_for_node(alias.name) or ""

    @staticmethod
    def _fix_last_comma(aliases: list[cst.ImportAlias]) -> list[cst.ImportAlias]:
        aliases[-1] = aliases[-1].with_changes(comma=cst.MaybeSentinel.DEFAULT)
        return aliases

    def leave_ImportFrom(
        self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom
    ) -> cst.BaseSmallStatement | cst.RemovalSentinel:
        module = updated_node.module
        names = updated_node.names
        if (
            updated_node.relative
            or not isinstance(module, cst.Name)
            or module.value not in TYPING_MODULES
            or isinstance(names, cst.ImportStar)
        ):
            return updated_node
        kept = [alias for alias in names if self._bound_name(alias) in self.used]
        if len(kept) == len(names):
            return updated_node
        if not kept:
            return cst.RemoveFromParent()
        return updated_node.with_changes(names=self._fix_last_comma(kept))

    def leave_Import(
        self, original_node: cst.Import, updated_node: cst.Import
    ) -> cst.BaseSmallStatement | cst.RemovalSentinel:
        kept: list[cst.ImportAlias] = []
        for alias in updated_node.names:
            full = get_full_name_for_node(alias.name)
            if full in TYPING_MODULES and self._bound_name(alias) not in self.used:
                continue
            kept.append(alias)
        if len(kept) == len(updated_node.names):
            return updated_node
        if not kept:
            return cst.RemoveFromParent()
        return updated_node.with_changes(names=self._fix_last_comma(kept))

    def leave_SimpleStatementLine(
        self, original_node: cst.SimpleStatementLine, updated_node: cst.SimpleStatementLine
    ) -> cst.BaseStatement | cst.RemovalSentinel:
        return updated_node if updated_node.body else cst.RemoveFromParent()


@dataclass(frozen=True, slots=True)
class CleanOutcome:
    """Result of ``clean_source``."""

    code: str
    comments_removed: int
    docstrings_removed: int
    hints_removed: int


def clean_source(source: str, config: CleanerConfig) -> CleanOutcome:
    """Parse ``source`` with LibCST, apply the transformers and render the result.

    Raises ``libcst.ParserSyntaxError`` if the source cannot be parsed.
    """
    module = cst.parse_module(source)
    cleaner = SourceCleaner(config)
    module = module.visit(cleaner)
    if config.strip_type_hints:
        collector = _NameCollector()
        module.visit(collector)
        module = module.visit(_UnusedTypingImportRemover(frozenset(collector.used)))
    return CleanOutcome(
        module.code,
        cleaner.comments_removed,
        cleaner.docstrings_removed,
        cleaner.hints_removed,
    )


# --------------------------------------------------------------------------- #
# File pipeline (runs inside worker processes; must not log)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class DecodedSource:
    """Decoded file content plus what is needed to re-encode it faithfully."""

    text: str
    encoding: str
    bom: bool

    def encode(self, text: str) -> bytes:
        data = text.encode(self.encoding)
        return codecs.BOM_UTF8 + data if self.bom else data


def decode_source(raw: bytes) -> DecodedSource:
    """Decode as UTF-8, falling back to a PEP 263 cookie encoding, then cp1252.

    Raises ``ValueError`` if no candidate encoding can decode the bytes.
    """
    bom = raw.startswith(codecs.BOM_UTF8)
    payload = raw[len(codecs.BOM_UTF8) :] if bom else raw
    candidates: list[str] = []
    try:
        cookie, _ = tokenize.detect_encoding(io.BytesIO(payload).readline)
        if not cookie.startswith("utf-8"):
            candidates.append(cookie)
    except (SyntaxError, LookupError):
        pass
    candidates += ["utf-8", "cp1252"]
    for encoding in dict.fromkeys(candidates):
        try:
            return DecodedSource(payload.decode(encoding), encoding, bom)
        except (UnicodeDecodeError, LookupError):
            continue
    raise ValueError("could not decode file as utf-8, its declared encoding, or cp1252")


def is_python_file(path: Path) -> bool:
    """Known suffix, or no suffix and a ``#!...python`` shebang."""
    if path.suffix in PYTHON_SUFFIXES:
        return True
    if path.suffix:
        return False
    try:
        with path.open("rb") as handle:
            first = handle.readline(256)
    except OSError:
        return False
    return first.startswith(b"#!") and b"python" in first


def write_atomic(path: Path, data: bytes) -> None:
    """Write via a temp file in the same directory, preserving permissions."""
    target = path.resolve()
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        shutil.copymode(target, tmp_path)
        os.replace(tmp_path, target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def make_diff(path: str, before: str, after: str) -> str:
    """Unified diff text (uncolored)."""
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


@dataclass(frozen=True, slots=True)
class _WorkerState:
    config: CleanerConfig
    run: RunOptions


_STATE: _WorkerState | None = None


def _init_worker(config: CleanerConfig, run: RunOptions) -> None:
    """Pool initializer: store shared settings and leave Ctrl-C to the parent."""
    global _STATE
    _STATE = _WorkerState(config, run)
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def process_file(path_str: str) -> FileResult:
    """Clean one file: decode, transform, validate, back up, write atomically.

    Every failure is converted into an ``error`` result so one bad file never
    aborts the run.  The original file is only replaced after the new source
    passed ``ast.parse`` for Python 3.12.
    """
    state = _STATE
    if state is None:  # pragma: no cover - defensive
        return FileResult(path_str, "error", message="worker not initialised")
    path = Path(path_str)
    try:
        raw = path.read_bytes()
    except PermissionError as exc:
        return FileResult(path_str, "error", message=f"permission denied: {exc}")
    except OSError as exc:
        return FileResult(path_str, "error", message=f"cannot read: {exc}")

    notes: list[str] = []
    try:
        decoded = decode_source(raw)
        if decoded.encoding != "utf-8":
            notes.append(f"decoded as {decoded.encoding}; will be written back in that encoding")
        outcome = clean_source(decoded.text, state.config)
    except ValueError as exc:
        return FileResult(path_str, "error", message=str(exc))
    except cst.ParserSyntaxError as exc:
        return FileResult(path_str, "error", message=f"cannot parse: {exc}")
    except Exception as exc:  # noqa: BLE001 - isolate per-file failures
        return FileResult(path_str, "error", message=f"transformer failed: {exc!r}")

    if outcome.code == decoded.text:
        return FileResult(path_str, "unchanged", message="; ".join(notes))

    try:
        ast.parse(outcome.code, filename=path_str, feature_version=TARGET_VERSION)
    except (SyntaxError, ValueError, RecursionError) as exc:
        return FileResult(path_str, "error", message=f"output is invalid Python, skipped: {exc}")

    try:
        new_raw = decoded.encode(outcome.code)
        diff = ""
        if state.run.want_diff or state.run.dry_run:
            diff = make_diff(path_str, decoded.text, outcome.code)
        if not state.run.dry_run:
            if state.run.backup:
                backup = path.with_name(path.name + ".bak")
                if backup.exists():
                    notes.append("existing .bak kept (not overwritten)")
                else:
                    shutil.copy2(path, backup)
            write_atomic(path, new_raw)
    except PermissionError as exc:
        return FileResult(path_str, "error", message=f"permission denied: {exc}")
    except (OSError, UnicodeEncodeError) as exc:
        return FileResult(path_str, "error", message=f"write failed: {exc}")

    return FileResult(
        path_str,
        "changed",
        comments_removed=outcome.comments_removed,
        docstrings_removed=outcome.docstrings_removed,
        hints_removed=outcome.hints_removed,
        bytes_saved=len(raw) - len(new_raw),
        message="; ".join(notes),
        diff=diff,
    )


# --------------------------------------------------------------------------- #
# File discovery and .ignore handling
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _Rule:
    pattern: str
    dir_only: bool
    anchored: bool


class IgnoreMatcher:
    """Small gitignore-like matcher built on ``fnmatch``.

    Supported: ``#`` comments, ``name`` / ``*.glob`` (matches any path
    component), ``dir/`` (directories only) and ``a/b`` (anchored to the root).
    No negation (``!``) support.
    """

    def __init__(self, patterns: Iterable[str]) -> None:
        self._rules: list[_Rule] = []
        for line in patterns:
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            dir_only = text.endswith("/")
            text = text.rstrip("/")
            anchored = "/" in text
            text = text.lstrip("/")
            if text:
                self._rules.append(_Rule(text, dir_only, anchored))

    def matches(self, parts: Sequence[str], is_dir: bool) -> bool:
        """``parts`` is the path relative to the scan root."""
        for rule in self._rules:
            for end in range(1, len(parts) + 1):
                if rule.dir_only and end == len(parts) and not is_dir:
                    continue
                candidate = "/".join(parts[:end]) if rule.anchored else parts[end - 1]
                if fnmatch.fnmatchcase(candidate, rule.pattern):
                    return True
        return False


def _read_ignore_file(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning(f"cannot read ignore file {path}: {exc}")
        return []


def discover_files(inputs: Sequence[Path], extra_patterns: Sequence[str], ignore_file: Path | None) -> list[str]:
    """Return the sorted-per-root list of Python files to process (deduplicated)."""
    seen: set[Path] = set()
    found: list[str] = []

    def add(path: Path) -> None:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            found.append(str(path))

    for root in inputs:
        if root.is_file():
            if is_python_file(root):
                add(root)
            else:
                logger.warning(f"{root}: not a Python file (no .py suffix or python shebang), skipped")
            continue
        if not root.is_dir():
            logger.error(f"{root}: no such file or directory")
            continue
        patterns = [*DEFAULT_IGNORES, *extra_patterns, *_read_ignore_file(root / IGNORE_FILENAME)]
        if ignore_file is not None:
            patterns += _read_ignore_file(ignore_file)
        matcher = IgnoreMatcher(patterns)
        for dirpath, dirnames, filenames in root.walk():
            rel_dir = dirpath.relative_to(root).parts
            dirnames[:] = sorted(d for d in dirnames if not matcher.matches((*rel_dir, d), True))
            for name in sorted(filenames):
                if matcher.matches((*rel_dir, name), False):
                    continue
                candidate = dirpath / name
                if is_python_file(candidate):
                    add(candidate)
    return found


# --------------------------------------------------------------------------- #
# Multiprocessing executor
# --------------------------------------------------------------------------- #


class PoolExecutor:
    """Runs ``process_file`` over many paths with exactly ``WORKERS`` processes.

    * ``map``            -- all results arrive at the end (no live progress).
    * ``imap``           -- ordered, lazy, chunked.
    * ``imap_unordered`` -- fastest; results as they finish.
    * ``apply``          -- one blocking call at a time (effectively serial).
    * ``apply_async``    -- bounded window of in-flight tasks, ordered results.
    """

    def __init__(self, method: PoolMethod, config: CleanerConfig, run: RunOptions) -> None:
        self.method = method
        self.config = config
        self.run = run

    def execute(self, files: Sequence[str], on_result: Callable[[FileResult], None]) -> None:
        chunksize = max(1, min(64, len(files) // (WORKERS * 4)))
        context = multiprocessing.get_context()
        with context.Pool(
            processes=WORKERS,
            initializer=_init_worker,
            initargs=(self.config, self.run),
        ) as pool:
            if self.method == "map":
                for result in pool.map(process_file, files, chunksize):
                    on_result(result)
            elif self.method == "imap":
                for result in pool.imap(process_file, files, chunksize):
                    on_result(result)
            elif self.method == "imap_unordered":
                for result in pool.imap_unordered(process_file, files, chunksize):
                    on_result(result)
            elif self.method == "apply":
                for path in files:
                    on_result(pool.apply(process_file, (path,)))
            else:
                window = WORKERS * 4
                pending: deque[AsyncResult[FileResult]] = deque()
                for path in files:
                    pending.append(pool.apply_async(process_file, (path,)))
                    while len(pending) >= window:
                        on_result(pending.popleft().get())
                while pending:
                    on_result(pending.popleft().get())


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Totals:
    """Aggregated run statistics."""

    scanned: int = 0
    changed: int = 0
    unchanged: int = 0
    errors: int = 0
    comments: int = 0
    docstrings: int = 0
    hints: int = 0
    bytes_saved: int = 0
    rows: list[FileResult] = field(default_factory=list)

    def add(self, result: FileResult) -> None:
        self.scanned += 1
        if result.status == "error":
            self.errors += 1
        elif result.status == "unchanged":
            self.unchanged += 1
        else:
            self.changed += 1
            self.comments += result.comments_removed
            self.docstrings += result.docstrings_removed
            self.hints += result.hints_removed
            self.bytes_saved += result.bytes_saved
            self.rows.append(replace(result, diff=""))


def use_color() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def colorize_diff(diff: str) -> str:
    """Add ANSI colors to unified diff text."""
    palette = {"+++": "1", "---": "1", "@@": "36", "+": "32", "-": "31"}
    lines: list[str] = []
    for line in diff.splitlines():
        code = next((c for prefix, c in palette.items() if line.startswith(prefix)), None)
        lines.append(f"\033[{code}m{line}\033[0m" if code else line)
    return "\n".join(lines)


def print_stats(totals: Totals, dry_run: bool) -> None:
    """Print the per-file table and totals for ``--stats``."""
    header = f"{'file':<60} {'comments':>9} {'docstrings':>11} {'hints':>6} {'bytes saved':>12}"
    print("\n" + header)
    print("-" * len(header))
    for row in totals.rows:
        name = row.path if len(row.path) <= 60 else "..." + row.path[-57:]
        print(
            f"{name:<60} {row.comments_removed:>9} {row.docstrings_removed:>11} "
            f"{row.hints_removed:>6} {row.bytes_saved:>12}"
        )
    print("-" * len(header))
    print(f"{'TOTAL':<60} {totals.comments:>9} {totals.docstrings:>11} {totals.hints:>6} {totals.bytes_saved:>12}")
    if dry_run:
        print("(dry run: nothing was written; numbers are what would change)")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyclean",
        description="Strip comments, docstrings and type hints from Python files using LibCST.",
        epilog=(
            "By default only inline comments are removed. Shebangs, '# type:' and "
            "'# fmt:' comments, and blocks that look like commented-out code are "
            "preserved unless --all is given."
        ),
    )
    parser.add_argument("paths", nargs="*", type=Path, help="files or directories (default: cwd)")
    parser.add_argument("-c", "--strip-comments", action="store_true", help="also remove full-line comment blocks")
    parser.add_argument("-d", "--strip-docstrings", action="store_true", help="remove docstrings")
    parser.add_argument(
        "-t", "--strip-type-hints", action="store_true", help="remove annotations and now-unused typing imports"
    )
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        dest="everything",
        help="strip everything, including shebangs and protected comments",
    )
    parser.add_argument(
        "--pool-method",
        choices=POOL_METHODS,
        default="apply_async",
        help="multiprocessing dispatch method (default: apply_async)",
    )
    parser.add_argument("--backup", action="store_true", help="write a .bak copy before modifying")
    parser.add_argument("--dry-run", action="store_true", help="show proposed changes (as a diff) without writing")
    parser.add_argument("--diff", action="store_true", help="print a colorized diff of each change")
    parser.add_argument("-n", "--stats", action="store_true", help="print a per-file/total report")
    parser.add_argument(
        "--ignore", action="append", default=[], metavar="PATTERN", help="extra ignore pattern (repeatable)"
    )
    parser.add_argument(
        "--ignore-file",
        type=Path,
        metavar="FILE",
        help=f"additional ignore file (a '{IGNORE_FILENAME}' in each scanned directory is always read)",
    )
    parser.add_argument("--no-progress", action="store_true", help="disable the progress bar")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return parser


def configure_logging(verbose: bool) -> None:
    """Route loguru through ``tqdm.write`` so logs do not corrupt the progress bar."""
    logger.remove()
    logger.add(
        lambda message: tqdm.write(str(message), end="", file=sys.stderr),
        level="DEBUG" if verbose else "INFO",
        colorize=sys.stderr.isatty(),
        format="<level>{level: <8}</level> {message}",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.  Returns 0 on success, 1 if any file failed, 130 on Ctrl-C."""
    if sys.version_info < (3, 12):
        print("pyclean requires Python 3.12 or newer", file=sys.stderr)
        return 2
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)

    config = CleanerConfig.from_flags(
        comments=args.strip_comments,
        docstrings=args.strip_docstrings,
        type_hints=args.strip_type_hints,
        everything=args.everything,
    )
    run = RunOptions(
        backup=args.backup and not args.dry_run,
        dry_run=args.dry_run,
        want_diff=args.diff,
    )
    if args.backup and args.dry_run:
        logger.info("--backup ignored in --dry-run mode")

    files = discover_files(args.paths or [Path.cwd()], args.ignore, args.ignore_file)
    if not files:
        logger.warning("no Python files found")
        return 0
    logger.info(f"processing {len(files)} file(s) with {WORKERS} workers ({args.pool_method})")

    totals = Totals()
    colorize = use_color()
    show_diff = args.diff or args.dry_run
    bar = tqdm(total=len(files), unit="file", disable=args.no_progress, file=sys.stderr)

    def handle(result: FileResult) -> None:
        bar.update(1)
        totals.add(result)
        if result.status == "error":
            logger.error(f"{result.path}: {result.message}")
            return
        if result.message:
            logger.warning(f"{result.path}: {result.message}")
        if result.status == "changed":
            verb = "would change" if run.dry_run else "cleaned"
            logger.debug(f"{verb} {result.path} (saved {result.bytes_saved} bytes)")
            if show_diff and result.diff:
                tqdm.write(colorize_diff(result.diff) if colorize else result.diff, end="\n")

    try:
        with bar:
            PoolExecutor(args.pool_method, config, run).execute(files, handle)
    except KeyboardInterrupt:
        logger.error("interrupted; workers terminated (completed files were already written)")
        return 130

    verb = "would be changed" if run.dry_run else "changed"
    logger.info(
        f"{totals.changed} file(s) {verb}, {totals.unchanged} unchanged, "
        f"{totals.errors} error(s); {totals.bytes_saved} bytes saved"
    )
    if args.stats:
        print_stats(totals, run.dry_run)
    return 1 if totals.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
