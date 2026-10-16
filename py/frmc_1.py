#!/data/data/com.termux/files/usr/bin/python
"""Write a Python script that scans a directory tree and identifies files that should be excluded from some downstream processing (such as code analysis,
linting,
or indexing),
using a configurable set of rules. The script should walk the directory structure starting from a root path provided by the user,
skipping well-known tooling,
dependency,
cache,
and version-control directories (for example,
git metadata,
virtual environments,
build outputs,
editor settings,
and package caches). Within the remaining files,
it should classify each file by its extension and filename: certain extensions and specific filenames (such as configuration files,
markup and documentation formats,
data files,
and many language sources that are not the target of processing) must be filtered out,
while files whose names or extensions are on an explicit processing list (for example,
build files like Makefiles) must be kept or flagged for processing.
The script should take a root directory and optional settings from the command line,
and produce a clear result: a list of the files selected for processing,
with an option to output them to the console or to a file,
and a summary of how many files were scanned,
selected,
and skipped. It should handle large directory trees efficiently by taking advantage of parallel processing where it helps,
gracefully handle unreadable paths,
permission errors,
and symbolic links without crashing,
and report errors in a concise way. Extension and name matching should be case-insensitive where appropriate,
and the set of skipped directories,
skipped extensions,
skipped filenames,
and processed filenames should be easy to extend or override without modifying the core logic. The script should exit with a meaningful status code: zero on success,
a non-zero code on invalid input or fatal errors.
---"""

from __future__ import annotations
import os
from pathlib import Path
import sys


SKIP_DIRS: frozenset[str] = frozenset({
    ".git",
    ".hg",
    ".svn",
    ".bzr",
    ".tox",
    ".nox",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".idea",
    ".vscode",
    ".cache",
    ".terraform",
    ".gradle",
    ".egg-info",
})
SKIP_EXTS: frozenset[str] = frozenset({
    ".yaml",
    ".yml",
    ".toml",
    ".py",
    ".pyi",
    ".pyw",
    ".rb",
    ".pl",
    ".pm",
    ".r",
    ".jl",
    ".ex",
    ".exs",
    ".cr",
    ".nim",
    ".ps1",
    ".psm1",
    ".php",
    ".coffee",
    ".hx",
    ".wl",
    ".wls",
    ".tex",
    ".ltx",
    ".f",
    ".f77",
    ".f90",
    ".f95",
    ".for",
    ".ftn",
    ".gd",
    ".hy",
    ".clj",
    ".cljs",
    ".cljc",
    ".md",
    ".markdown",
    ".rst",
    ".adoc",
    ".asciidoc",
    ".rdf",
    ".ttl",
    ".sparql",
    ".cql",
    ".cypher",
    ".graphql",
    ".gql",
    ".json5",
    ".jsonc",
    ".hjson",
    ".csv",
    ".tsv",
    ".properties",
    ".asm",
    ".s",
    ".v",
    ".vh",
    ".vhd",
    ".vhdl",
    ".sv",
    ".svh",
    ".vim",
    ".sql",
    ".mysql",
})
SKIP_NAMES: frozenset[str] = frozenset({
    "requirements.in",
})
PROCESS_NAMES: frozenset[str] = frozenset({
    "Makefile",
    "makefile",
    "GNUmakefile",
    "Dockerfile",
    "crontab",
    "requirements.txt",
    "pip.conf",
    "setup.cfg",
    ".editorconfig",
    ".npmrc",
    ".pylintrc",
    ".gitconfig",
    ".gitignore",
    ".gitattributes",
    "nginx.conf",
    "httpd.conf",
})
PROCESS_EXTS: frozenset[str] = frozenset({
    ".zsh",
    ".ksh",
    ".fish",
    ".csh",
    ".tcsh",
    ".awk",
    ".sed",
    ".tcl",
    ".exp",
    ".ini",
    ".conf",
    ".cfg",
    ".cnf",
    ".service",
    ".socket",
    ".timer",
    ".target",
    ".mount",
    ".path",
    ".pp",
    ".desktop",
})
PROCESS_PREFIXES: tuple[str, ...] = ("Makefile", "Dockerfile", ".env")


def is_processable(p: Path) -> bool:
    name = p.name
    suffix = p.suffix.lower()
    if suffix in SKIP_EXTS:
        return False
    if name in SKIP_NAMES:
        return False
    if name in PROCESS_NAMES:
        return True
    if suffix in PROCESS_EXTS:
        return True
    return any(name.startswith(prefix) for prefix in PROCESS_PREFIXES)


def is_allowed(p: Path, explicit: bool) -> bool:
    if p.suffix.lower() in SKIP_EXTS:
        return False
    if p.name in SKIP_NAMES:
        return False
    if explicit:
        return True
    return is_processable(p)


def strip_comment(body: str) -> str:
    if body.lstrip().startswith("#!"):
        return body
    out: list[str] = []
    i = 0
    n = len(body)
    quote = ""
    while i < n:
        c = body[i]
        if quote:
            out.append(c)
            if c == "\\" and quote == '"' and i + 1 < n:
                out.append(body[i + 1])
                i += 2
                continue
            if c == quote:
                quote = ""
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            out.append(c)
            out.append(body[i + 1])
            i += 2
            continue
        if c in {"'", '"'}:
            quote = c
            out.append(c)
            i += 1
            continue
        if c == "#":
            break
        out.append(c)
        i += 1
    return "".join(out).rstrip()


def process_file(path_str: str) -> tuple[str, int] | None:
    p = Path(path_str)
    try:
        data = p.read_bytes()
    except OSError:
        return None
    if b"\x00" in data:
        return None
    original_size = len(data)
    encoding = "utf-8"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            encoding = "latin-1"
            text = data.decode("latin-1")
        except Exception:
            return None
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    changed = False
    for line in lines:
        if line.endswith("\r\n"):
            body, nl = line[:-2], "\r\n"
        elif line.endswith("\n"):
            body, nl = line[:-1], "\n"
        elif line.endswith("\r"):
            body, nl = line[:-1], "\r"
        else:
            body, nl = line, ""
        new_body = strip_comment(body)
        if new_body == body:
            out.append(line)
            continue
        changed = True
        if new_body == "" and body.strip() != "":
            continue
        out.append(new_body + nl)
    if not changed:
        return (path_str, 0)
    new_text = "".join(out)
    try:
        new_data = new_text.encode(encoding)
    except UnicodeEncodeError:
        return None
    if new_data == data:
        return (path_str, 0)
    try:
        p.write_bytes(new_data)
    except OSError:
        return None
    saved = original_size - len(new_data)
    return (path_str, max(0, saved))


def collect_files(roots: list[Path]) -> tuple[list[Path], set[str]]:
    files: list[Path] = []
    explicit: set[str] = set()
    seen: set[str] = set()

    def add(p: Path, is_explicit: bool) -> None:
        key = os.path.realpath(p)
        if key in seen:
            if is_explicit:
                explicit.add(key)
            return
        seen.add(key)
        files.append(p)
        if is_explicit:
            explicit.add(key)

    for root in roots:
        try:
            if root.is_symlink():
                continue
        except OSError:
            continue
        if root.is_file():
            add(root, True)
            continue
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            kept: list[str] = []
            for d in dirnames:
                if d in SKIP_DIRS:
                    continue
                dp = Path(dirpath) / d
                try:
                    if dp.is_symlink():
                        continue
                except OSError:
                    continue
                kept.append(d)
            dirnames[:] = kept
            for fn in filenames:
                fp = Path(dirpath) / fn
                try:
                    if fp.is_symlink():
                        continue
                except OSError:
                    continue
                add(fp, False)
    return files, explicit


def main(argv: list[str]) -> int:
    args = argv[1:]
    if args:
        roots = [Path(a) for a in args]
    else:
        roots = [Path.cwd()]
    all_files, explicit = collect_files(roots)
    targets: list[Path] = []
    for f in all_files:
        key = os.path.realpath(f)
        if is_allowed(f, key in explicit):
            targets.append(f)
    use_color = sys.stdout.isatty()
    green = "\033[32m" if use_color else ""
    reset = "\033[0m" if use_color else ""
    cwd = Path.cwd()
    results: list[tuple[str, int]] = []
    if len(targets) == 1:
        r = process_file(str(targets[0]))
