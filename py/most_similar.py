#!/data/data/com.termux/files/usr/bin/python
"""Find the top-N most similar files in ~/bin to a given file using ssdeep.

Python sources are normalized before hashing: shebang, comments, docstrings,
and type annotations are removed so similarity reflects structure, not
formatting/comment noise.

Targets Python 3.14+:
  * pathlib.Path.walk for traversal
  * selectable multiprocessing backend via --mp-method
    (serial | interpreter | process | thread | auto)

Optimizations:
  * persistent hash cache keyed by (path, mtime_ns, size)
  * single lstat per file; symlinks and specials skipped
  * atomic cache writes; cache failures are non-fatal
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import stat
import sys
from concurrent.futures import (
    Executor,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
)
from pathlib import Path
from typing import Iterator

try:
    from concurrent.futures import InterpreterPoolExecutor
    _HAVE_INTERPRETER = True
except ImportError:  # pragma: no cover — only on <3.14
    InterpreterPoolExecutor = None  # type: ignore[assignment]
    _HAVE_INTERPRETER = False

import ssdeep

SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", "__pycache__", "node_modules",
    ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache",
    ".cache", ".idea", ".vscode",
})

CACHE_VERSION = 1
_CACHE_BASE = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache"))
CACHE_PATH = _CACHE_BASE / "bin-similar" / "ssdeep-hashes.json"

# Below this many uncached jobs, `auto` stays serial.
PARALLEL_THRESHOLD = 8

MP_METHODS = ("auto", "serial", "interpreter", "process", "thread")


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #

class _Normalizer(ast.NodeTransformer):
    """Strip docstrings and type annotations from a Python AST."""

    @staticmethod
    def _strip_docstring(node):
        body = getattr(node, "body", None)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]
        return node

    @staticmethod
    def _clear_arg_annotations(args: ast.arguments) -> None:
        for a in (*args.posonlyargs, *args.args, *args.kwonlyargs):
            a.annotation = None
        if args.vararg:
            args.vararg.annotation = None
        if args.kwarg:
            args.kwarg.annotation = None

    def visit_Module(self, node):
        self.generic_visit(node)
        return self._strip_docstring(node)

    def _visit_func(self, node):
        self.generic_visit(node)
        node.returns = None
        self._clear_arg_annotations(node.args)
        return self._strip_docstring(node)

    visit_FunctionDef = _visit_func
    visit_AsyncFunctionDef = _visit_func

    def visit_ClassDef(self, node):
        self.generic_visit(node)
        return self._strip_docstring(node)

    def visit_AnnAssign(self, node):
        # `x: int = 1` -> `x = 1`  ;  bare `x: int` -> drop entirely
        self.generic_visit(node)
        if node.value is not None:
            return ast.copy_location(
                ast.Assign(targets=[node.target], value=node.value), node
            )
        return ast.copy_location(ast.Pass(), node)


def normalize_python(source: str) -> str:
    """Return normalized source: no shebang, comments (dropped by AST),
    docstrings, or type annotations. Falls back to raw text if unparseable."""
    lines = source.splitlines()
    if lines and lines[0].startswith("#!"):
        lines = lines[1:]
    src = "\n".join(lines)

    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src

    tree = _Normalizer().visit(tree)
    ast.fix_missing_locations(tree)
    try:
        return ast.unparse(tree)
    except Exception:
        return src


# --------------------------------------------------------------------------- #
# File discovery
# --------------------------------------------------------------------------- #

def iter_files(root: Path) -> Iterator[tuple[Path, int, int]]:
    """Yield (path, mtime_ns, size) for regular files under root."""
    for dirpath, dirnames, filenames in root.walk():
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            p = dirpath / name
            try:
                st = p.lstat()
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):  # skips symlinks, FIFOs, etc.
                continue
            yield p, st.st_mtime_ns, st.st_size


# --------------------------------------------------------------------------- #
# Hashing worker
# --------------------------------------------------------------------------- #

def _hash_job(job: tuple[Path, int, int]) -> tuple[Path, int, int, str | None]:
    """Must be module-level so it's picklable for process/interpreter pools."""
    path, mtime_ns, size = job
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        h = ssdeep.hash(normalize_python(src))
    except Exception:
        h = None
    return path, mtime_ns, size, h


# --------------------------------------------------------------------------- #
# Multiprocessing backends
# --------------------------------------------------------------------------- #

def _default_parallel() -> str:
    return "interpreter" if _HAVE_INTERPRETER else "process"


def _resolve_method(requested: str, n_jobs: int) -> str:
    """Turn `auto` into a concrete method; pass others through."""
    if requested != "auto":
        if requested == "interpreter" and not _HAVE_INTERPRETER:
            raise RuntimeError(
                "InterpreterPoolExecutor unavailable (need Python 3.14+)"
            )
        return requested
    if n_jobs < PARALLEL_THRESHOLD:
        return "serial"
    return _default_parallel()


def _make_executor(method: str, workers: int | None) -> Executor | None:
    match method:
        case "serial":
            return None
        case "interpreter":
            return InterpreterPoolExecutor(max_workers=workers)
        case "process":
            return ProcessPoolExecutor(max_workers=workers)
        case "thread":
            return ThreadPoolExecutor(max_workers=workers)
        case _:
            raise ValueError(f"unknown mp method: {method!r}")


def _hash_all(
    jobs: list[tuple[Path, int, int]],
    method: str,
    workers: int | None,
) -> list[tuple[Path, int, int, str | None]]:
    if not jobs:
        return []
    ex = _make_executor(method, workers)
    if ex is None:
        return [_hash_job(j) for j in jobs]
    with ex:
        # Sub-interpreters use pickling; keep the same call shape for all.
        return list(ex.map(_hash_job, jobs))


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #

def _load_cache(path: Path) -> dict[str, list]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    if data.get("version") != CACHE_VERSION:
        return {}
    entries = data.get("entries")
    return entries if isinstance(entries, dict) else {}


def _save_cache(path: Path, entries: dict[str, list]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump({"version": CACHE_VERSION, "entries": entries}, f)
        os.replace(tmp, path)
    except Exception:
        pass  # cache is best-effort


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog=Path(argv[0]).name,
        description="Find the most similar files in ~/bin to a given file.",
    )
    ap.add_argument("file", type=Path, help="file to compare against")
    ap.add_argument(
        "--mp-method",
        choices=MP_METHODS,
        default="auto",
        help="parallel backend (default: auto)",
    )
    ap.add_argument(
        "-j", "--workers",
        type=int,
        default=None,
        help="max workers for parallel methods (default: executor default)",
    )
    ap.add_argument(
        "--bin-dir",
        type=Path,
        default=Path.home() / "bin",
        help="directory to search (default: ~/bin)",
    )
    ap.add_argument(
        "--top",
        type=int,
        default=3,
        help="number of results to show (default: 3)",
    )
    return ap.parse_args(argv[1:])


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv
    args = parse_args(argv)

    target = args.file.expanduser()
    if not target.is_file():
        print(f"error: not a file: {target}", file=sys.stderr)
        return 1
    target = target.resolve()

    try:
        target_src = target.read_text(encoding="utf-8", errors="replace")
        target_hash = ssdeep.hash(normalize_python(target_src))
    except Exception as e:
        print(f"error: cannot hash {target}: {e}", file=sys.stderr)
        return 1

    bin_dir = args.bin_dir.expanduser().resolve()
    if not bin_dir.is_dir():
        print(f"error: no such directory: {bin_dir}", file=sys.stderr)
        return 1

    files = list(iter_files(bin_dir))
    if not files:
        print(f"no files found under {bin_dir}", file=sys.stderr)
        return 1

    cache = _load_cache(CACHE_PATH)
    hashes: dict[Path, str] = {}
    to_hash: list[tuple[Path, int, int]] = []
    seen: set[Path] = set()

    for path, mtime_ns, size in files:
        seen.add(path)
        ent = cache.get(str(path))
        # ent = [mtime_ns, size, hash]
        if ent and len(ent) == 3 and ent[0] == mtime_ns and ent[1] == size:
            hashes[path] = ent[2]
        else:
            to_hash.append((path, mtime_ns, size))

    method = _resolve_method(args.mp_method, len(to_hash))

    for path, mtime_ns, size, h in _hash_all(to_hash, method, args.workers):
        if h is None:
            cache.pop(str(path), None)
            continue
        hashes[path] = h
        cache[str(path)] = [mtime_ns, size, h]

    # Prune cache entries for files that no longer exist.
    for gone in [k for k in cache if Path(k) not in seen]:
        del cache[gone]

    _save_cache(CACHE_PATH, cache)

    scored: list[tuple[int, Path]] = []
    for path, h in hashes.items():
        if path == target:
            continue
        try:
            score = ssdeep.compare(target_hash, h)
        except Exception:
            continue
        scored.append((score, path))

    if not scored:
        print("no comparable files found")
        return 0

    scored.sort(key=lambda t: (-t[0], str(t[1])))
    for score, path in scored[: args.top]:
        print(f"{score:>3}%  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
