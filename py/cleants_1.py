#!/data/data/com.termux/files/usr/bin/python
from __future__ import annotations

import argparse
import difflib
import importlib
import multiprocessing as mp
import os
import re
import shutil
import sys
from collections import Counter
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Iterator

from tree_sitter import Language, Parser, Tree, Node


@dataclass(frozen=True, slots=True)
class LangSpec:
    module: str
    attr: str
    comment_types: frozenset[str]


_LANG_ATTR = "language"

LANGUAGES: dict[str, LangSpec] = {
    "bash": LangSpec("tree_sitter_bash", _LANG_ATTR, frozenset({"comment"})),
    "c": LangSpec("tree_sitter_c", _LANG_ATTR, frozenset({"comment"})),
    "cpp": LangSpec("tree_sitter_cpp", _LANG_ATTR, frozenset({"comment"})),
    "css": LangSpec("tree_sitter_css", _LANG_ATTR, frozenset({"comment"})),
    "go": LangSpec("tree_sitter_go", _LANG_ATTR, frozenset({"comment"})),
    "html": LangSpec("tree_sitter_html", _LANG_ATTR, frozenset({"comment"})),
    "java": LangSpec("tree_sitter_java", _LANG_ATTR, frozenset({"line_comment", "block_comment"})),
    "javascript": LangSpec("tree_sitter_javascript", _LANG_ATTR, frozenset({"comment"})),
    "latex": LangSpec(
        "tree_sitter_latex",
        _LANG_ATTR,
        frozenset({"comment", "line_comment", "block_comment", "comment_environment"}),
    ),
    "lua": LangSpec("tree_sitter_lua", _LANG_ATTR, frozenset({"comment"})),
    "perl": LangSpec("tree_sitter_perl", _LANG_ATTR, frozenset({"comment"})),
    "php": LangSpec("tree_sitter_php", "language_php", frozenset({"comment"})),
    "python": LangSpec("tree_sitter_python", _LANG_ATTR, frozenset({"comment"})),
    "query": LangSpec("tree_sitter_query", _LANG_ATTR, frozenset({"comment"})),
    "rst": LangSpec("tree_sitter_rst", _LANG_ATTR, frozenset({"comment"})),
    "ruby": LangSpec("tree_sitter_ruby", _LANG_ATTR, frozenset({"comment"})),
    "rust": LangSpec("tree_sitter_rust", _LANG_ATTR, frozenset({"line_comment", "block_comment"})),
    "sql": LangSpec("tree_sitter_sql", _LANG_ATTR, frozenset({"comment"})),
    "toml": LangSpec("tree_sitter_toml", _LANG_ATTR, frozenset({"comment"})),
    "vim": LangSpec("tree_sitter_vim", _LANG_ATTR, frozenset({"comment"})),
    "xml": LangSpec("tree_sitter_xml", "language_xml", frozenset({"Comment", "comment"})),
    "yaml": LangSpec("tree_sitter_yaml", _LANG_ATTR, frozenset({"comment"})),
}

EXTENSIONS: dict[str, str] = {
    ".sh": "bash",
    ".bash": "bash",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hh": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".css": "css",
    ".go": "go",
    ".html": "html",
    ".htm": "html",
    ".java": "java",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".tex": "latex",
    ".sty": "latex",
    ".cls": "latex",
    ".lua": "lua",
    ".pl": "perl",
    ".pm": "perl",
    ".php": "php",
    ".py": "python",
    ".pyw": "python",
    ".scm": "query",
    ".rst": "rst",
    ".rb": "ruby",
    ".rs": "rust",
    ".sql": "sql",
    ".toml": "toml",
    ".vim": "vim",
    ".xml": "xml",
    ".svg": "xml",
    ".xsl": "xml",
    ".xsd": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
}

SHEBANG_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bpython[\d.]*\b"), "python"),
    (re.compile(r"\b(ba|z|k)?sh\b"), "bash"),
    (re.compile(r"\bnode\b"), "javascript"),
    (re.compile(r"\bperl\b"), "perl"),
    (re.compile(r"\bphp\b"), "php"),
    (re.compile(r"\bruby\b"), "ruby"),
    (re.compile(r"\blua\b"), "lua"),
]

VITAL_RE = re.compile(
    r"copyright|licen[cs]e|spdx|\(c\)\s*\d{4}|@preserve|@license|@ts-|@jsx|@flow|"
    r"eslint|jshint|prettier-ignore|noqa|type:\s*ignore|pylint:|pyright:|mypy:|pragma|"
    r"nolint|nosec|nosonar|fmt:\s*(on|off|skip)|coding[:=]\s*[-\w.]+|go:\w|\+build|"
    r"%!|\[if\b|/\*!|[#/]\s*(end)?region\b|sourceMappingURL|sourceURL",
    re.IGNORECASE,
)

DOC_PREFIXES = (b"/**", b"///", b"//!")

DEFAULT_EXCLUDES = frozenset({
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".ruff_cache",
    "build",
    "dist",
    "target",
})


@dataclass(frozen=True, slots=True)
class Options:
    diff: bool
    backup: bool
    backup_suffix: str
    dryrun: bool
    inplace: bool
    check: bool
    keep_doc: bool
    max_size: int


@dataclass(frozen=True, slots=True)
class Comment:
    start: int
    end: int
    kind: str


@dataclass(frozen=True, slots=True)
class Result:
    path: Path
    status: str
    removed: int = 0
    message: str = ""
    diff: str = ""


_parsers: dict[str, Parser] = {}


def get_parser(lang: str) -> Parser:
    parser = _parsers.get(lang)
    if parser is None:
        spec = LANGUAGES[lang]
        module = importlib.import_module(spec.module)
        parser = Parser(Language(getattr(module, spec.attr)()))
        _parsers[lang] = parser
    return parser


def detect_language(path: Path, head: bytes) -> str | None:
    suffix = path.suffix.lower()
    if suffix in EXTENSIONS:
        return EXTENSIONS[suffix]
    if head.startswith(b"#!"):
        first_line = head.split(b"\n", 1)[0].decode("utf-8", "replace")
        for pattern, lang in SHEBANG_RULES:
            if pattern.search(first_line):
                return lang
    return None


def collect_comments(root: Node, kinds: frozenset[str]) -> list[Comment]:
    found: list[Comment] = []
    stack: list[Node] = [root]
    while stack:
        node = stack.pop()
        if node.is_missing:
            continue
        if node.type in kinds:
            found.append(Comment(node.start_byte, node.end_byte, node.type))
            continue
        stack.extend(node.children)
    return found


def is_vital(src: bytes, comment: Comment, keep_doc: bool) -> bool:
    text = src[comment.start : comment.end]
    if comment.start == 0 and text.startswith(b"#!"):
        return True
    if VITAL_RE.search(text.decode("utf-8", "replace")):
        return True
    return keep_doc and text.startswith(DOC_PREFIXES) and text != b"/**/"


def strip_spans(src: bytes, spans: list[tuple[int, int]]) -> bytes:
    ranges: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        line_start = src.rfind(b"\n", 0, start) + 1
        newline = src.find(b"\n", end)
        line_end = len(src) if newline == -1 else newline
        if not src[line_start:start].strip() and not src[end:line_end].strip():
            ranges.append((line_start, min(line_end + 1, len(src))))
        else:
            cut = start
            while cut > line_start and src[cut - 1] in b" \t":
                cut -= 1
            ranges.append((cut, end))

    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    out = bytearray()
    pos = 0
    for start, end in merged:
        out += src[pos:start]
        pos = end
    out += src[pos:]
    return bytes(out)


def leaf_signatures(
    root: Node,
    src: bytes,
    kinds: frozenset[str],
    skip: frozenset[tuple[int, int]],
) -> list[tuple[str, bytes]]:
    signatures: list[tuple[str, bytes]] = []
    stack: list[Node] = [root]
    while stack:
        node = stack.pop()
        if node.type in kinds and (node.start_byte, node.end_byte) in skip:
            continue
        if node.child_count == 0:
            if not node.is_missing:
                signatures.append((node.type, src[node.start_byte : node.end_byte]))
            continue
        stack.extend(reversed(node.children))
    return signatures


def validate(
    old_tree: Tree,
    src: bytes,
    new_src: bytes,
    parser: Parser,
    kinds: frozenset[str],
    removed: frozenset[tuple[int, int]],
) -> str | None:
    new_tree = parser.parse(new_src)
    if new_tree.root_node.has_error and not old_tree.root_node.has_error:
        return "output introduces parse errors"
    before = leaf_signatures(old_tree.root_node, src, kinds, removed)
    after = leaf_signatures(new_tree.root_node, new_src, kinds, frozenset())
    if before != after:
        return "token stream changed beyond comment removal"
    return None


def write_atomic(target: Path, data: bytes, mode_from: Path) -> None:
    tmp = target.with_name(f".{target.name}.tmp")
    try:
        tmp.write_bytes(data)
        shutil.copymode(mode_from, tmp)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def process_file(path: Path, opts: Options) -> Result:
    try:
        if path.is_symlink() or not path.is_file():
            return Result(path, "skipped", message="not a regular file")
        if path.stat().st_size > opts.max_size:
            return Result(path, "skipped", message="exceeds max size")

        with path.open("rb") as fh:
            head = fh.read(256)
        lang = detect_language(path, head)
        if lang is None:
            return Result(path, "skipped", message="unsupported type")

        spec = LANGUAGES[lang]
        parser = get_parser(lang)
        src = path.read_bytes()
        tree = parser.parse(src)

        comments = collect_comments(tree.root_node, spec.comment_types)
        removable = [c for c in comments if not is_vital(src, c, opts.keep_doc)]
        if not removable:
            return Result(path, "unchanged")

        spans = [(c.start, c.end) for c in removable]
        new_src = strip_spans(src, spans)

        problem = validate(tree, src, new_src, parser, spec.comment_types, frozenset(spans))
        if problem:
            return Result(path, "rejected", message=problem)

        diff = ""
        if opts.diff:
            diff = "".join(
                difflib.unified_diff(
                    src.decode("utf-8", "replace").splitlines(True),
                    new_src.decode("utf-8", "replace").splitlines(True),
                    fromfile=str(path),
                    tofile=f"{path} (stripped)",
                )
            )

        if opts.dryrun or opts.check:
            return Result(path, "would-change", len(removable), diff=diff)

        if opts.inplace:
            target = path
            if opts.backup:
                shutil.copy2(path, path.with_name(path.name + opts.backup_suffix))
        else:
            target = path.with_name(f"{path.stem}.stripped{path.suffix}")

        write_atomic(target, new_src, mode_from=path)
        return Result(path, "changed", len(removable), diff=diff)

    except ImportError as exc:
        return Result(path, "skipped", message=f"grammar not installed: {exc.name}")
    except Exception as exc:
        return Result(path, "error", message=str(exc))


def iter_files(root: Path, excludes: frozenset[str]) -> Iterator[Path]:
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name not in excludes:
                    stack.append(entry)
            elif entry.is_file():
                yield entry


def discover(inputs: list[str], excludes: frozenset[str]) -> tuple[list[Path], list[str]]:
    files: list[Path] = []
    seen: set[Path] = set()
    problems: list[str] = []

    for raw in inputs:
        path = Path(raw)
        if path.is_symlink():
            problems.append(f"symlink skipped: {raw}")
            continue
        if not path.exists():
            problems.append(f"not found: {raw}")
            continue

        candidates: Iterator[Path]
        if path.is_file():
            candidates = iter([path])
        elif path.is_dir():
            candidates = iter_files(path, excludes)
        else:
            candidates = iter([])

        for candidate in candidates:
            key = candidate.resolve()
            if key not in seen:
                seen.add(key)
                files.append(candidate)

    return files, problems


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stripcomments",
        description="Strip comments from source files using tree-sitter, safely and in parallel.",
    )
    parser.add_argument("paths", nargs="*", default=["."], metavar="PATH")
    parser.add_argument("--inplace", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--dryrun", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--diff", action="store_true")
    parser.add_argument("--backup", action="store_true")
    parser.add_argument("--backup-suffix", default=".bak")
    parser.add_argument("--keep-doc", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--exclude", action="append", default=[], metavar="NAME")
    parser.add_argument("--max-size", type=int, default=5 * 1024 * 1024)
    parser.add_argument("--jobs", "-j", type=int, default=8)
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true")
    return parser


def emit(res: Result, quiet: bool, verbose: bool) -> None:
    if res.status in {"changed", "would-change"}:
        if not quiet:
            label = "stripped" if res.status == "changed" else "would strip"
            print(f"{label} {res.removed} comment(s): {res.path}")
        if res.diff:
            sys.stdout.write(res.diff)
    elif res.status in {"rejected", "error"}:
        print(f"{res.status}: {res.path}: {res.message}", file=sys.stderr)
    elif res.status == "unchanged" and verbose:
        print(f"unchanged: {res.path}")
    elif res.status == "skipped" and verbose:
        print(f"skipped: {res.path} ({res.message})")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error("--jobs must be >= 1")

    excludes = DEFAULT_EXCLUDES | frozenset(args.exclude)
    files, problems = discover(args.paths, excludes)
    for problem in problems:
        print(problem, file=sys.stderr)
    if not files:
        print("no candidate files found")
        return 2 if problems else 0

    opts = Options(
        diff=args.diff,
        backup=args.backup,
        backup_suffix=args.backup_suffix,
        dryrun=args.dryrun,
        inplace=args.inplace,
        check=args.check,
        keep_doc=args.keep_doc,
        max_size=args.max_size,
    )

    counts: Counter[str] = Counter()
    worker = partial(process_file, opts=opts)
    with mp.Pool(processes=args.jobs) as pool:
        for res in pool.imap_unordered(worker, files, chunksize=4):
            counts[res.status] += 1
            emit(res, args.quiet, args.verbose)

    if not args.quiet:
        summary = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
        print(f"done: {summary}")

    if counts["error"] or counts["rejected"] or problems:
        return 2
    if args.check and counts["would-change"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
