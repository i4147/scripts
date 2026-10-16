#!/usr/bin/env python3

from __future__ import annotations

import argparse
import difflib
import fnmatch
import json
import mmap
import os
import sys
import tempfile
from dataclasses import dataclass
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import Any, Sequence

# Files larger than 1MB are read using memory mapping (mmap)
MMAP_THRESHOLD = 1024 * 1024

# Recognized JSON extensions
JSON_EXTENSIONS = frozenset({".json", ".jsonc", ".tsconfig"})

# Default directory exclusion patterns
DEFAULT_EXCLUDES = frozenset({".git", ".venv", "venv", "__pycache__", "build", "dist"})


# =============================================================================
# BACKEND ABSTRACT BASE & IMPLEMENTATIONS
# =============================================================================


class _Backend:
    """Abstract base class for JSON parsing/serialization backends."""

    name: str = "json"

    def loads(self, text: str | bytes) -> Any:
        raise NotImplementedError

    def dumps(
        self,
        obj: Any,
        *,
        sort_keys: bool = False,
        compact: bool = False,
        indent: int | None = None,
    ) -> str:
        raise NotImplementedError


class _StdlibBackend(_Backend):
    """Standard library `json` backend (fallback)."""

    name = "stdlib"

    def loads(self, text: str | bytes) -> Any:
        return json.loads(text)

    def dumps(self, obj: Any, *, sort_keys: bool = False, compact: bool = False, indent: int | None = None) -> str:
        if indent is not None:
            return json.dumps(obj, ensure_ascii=False, sort_keys=sort_keys, indent=indent)
        if compact:
            return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=sort_keys)
        return json.dumps(obj, ensure_ascii=False, sort_keys=sort_keys, indent=PRETTY_INDENT_DEFAULT)


class _OrjsonBackend(_Backend):
    """High-performance `orjson` backend."""

    name = "orjson"

    def __init__(self) -> None:
        import orjson  # noqa: WPS433

        self._orjson = orjson

    def loads(self, text: str | bytes) -> Any:
        return self._orjson.loads(text)

    def dumps(self, obj: Any, *, sort_keys: bool = False, compact: bool = False, indent: int | None = None) -> str:
        opt = 0
        if sort_keys:
            opt |= self._orjson.OPT_SORT_KEYS
        if indent is not None and indent > 0:
            opt |= self._orjson.OPT_INDENT_2  # orjson natively supports 2-space indentation

        raw = self._orjson.dumps(obj, option=opt)
        return raw.decode("utf-8")


class _UjsonBackend(_Backend):
    """Fast `ujson` backend."""

    name = "ujson"

    def __init__(self) -> None:
        import ujson  # noqa: WPS433

        self._ujson = ujson

    def loads(self, text: str | bytes) -> Any:
        return self._ujson.loads(text)

    def dumps(self, obj: Any, *, sort_keys: bool = False, compact: bool = False, indent: int | None = None) -> str:
        kwargs: dict[str, Any] = {"ensure_ascii": False, "encode_html_chars": False}
        if indent is not None:
            kwargs["indent"] = indent
        elif compact:
            kwargs["separators"] = (",", ":")
        return self._ujson.dumps(obj, **kwargs)


def get_backend(requested: str = "auto") -> _Backend:
    """Instantiates and returns the requested backend engine."""
    backends: dict[str, type[_Backend]] = {
        "orjson": _OrjsonBackend,
        "ujson": _UjsonBackend,
        "stdlib": _StdlibBackend,
    }

    if requested != "auto":
        if requested not in backends:
            raise ValueError(f"Unknown backend '{requested}'. Choose from: auto, {', '.join(backends.keys())}")
        try:
            return backends[requested]()
        except ImportError as e:
            raise RuntimeError(f"Backend '{requested}' requested but required module is not installed: {e}") from e

    # Auto-detection priority order
    for cls in (_OrjsonBackend, _UjsonBackend):
        try:
            return cls()
        except ImportError:
            continue
    return _StdlibBackend()


PRETTY_INDENT_DEFAULT = 2


# =============================================================================
# DATA STRUCTURES & FORMATTING HELPERS
# =============================================================================


@dataclass(frozen=True)
class ProcessTask:
    """Task parameters sent to worker processes."""

    file_path: str
    minify: bool
    sort_keys: bool
    custom: bool
    indent: int
    check_only: bool
    show_diff: bool
    backup: bool
    backend_name: str


@dataclass(frozen=True)
class ProcessResult:
    """Structured result returned by a worker process."""

    file_path: str
    success: bool
    changed: bool
    diff: str | None = None
    error: str | None = None


def custom_format(data: Any, backend: _Backend, sort_keys: bool = False) -> str:
    """Formats JSON by expanding top-level containers while keeping nested items compact."""
    if isinstance(data, dict) and data:
        items = sorted(data.items()) if sort_keys else data.items()
        inner = ",\n  ".join(
            f"{backend.dumps(k, sort_keys=sort_keys)}: {backend.dumps(v, sort_keys=sort_keys)}" for k, v in items
        )
        return "{\n  " + inner + "\n}"

    if isinstance(data, list) and data:
        inner = ",\n  ".join(backend.dumps(v, sort_keys=sort_keys) for v in data)
        return "[\n  " + inner + "\n]"

    return backend.dumps(data, sort_keys=sort_keys)


def _read_file_content(path: Path) -> str:
    """Reads text content using mmap for large files or standard IO for smaller ones."""
    file_size = path.stat().st_size
    if file_size == 0:
        return ""
    if file_size > MMAP_THRESHOLD:
        with path.open("rb") as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                return mm.read().decode("utf-8")
    return path.read_text(encoding="utf-8")


def _atomic_write(path: Path, text: str, create_backup: bool = False) -> None:
    """Writes output atomically using a temporary file and optionally creates a backup."""
    if create_backup and path.exists():
        backup_path = path.with_suffix(path.suffix + ".bak")
        backup_path.write_bytes(path.read_bytes())

    original_mode = path.stat().st_mode if path.exists() else 0o644

    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp_path, original_mode)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


# =============================================================================
# FILE PROCESSING WORKER
# =============================================================================


def process_json_file(task: ProcessTask) -> ProcessResult:
    """Processes a single JSON file (runs inside multiprocessing worker)."""
    file_path = Path(task.file_path)
    backend = get_backend(task.backend_name)

    try:
        original_text = _read_file_content(file_path)
        data = backend.loads(original_text)

        # Generate target formatted string
        if task.minify:
            output = backend.dumps(data, sort_keys=task.sort_keys, compact=True)
        elif task.custom:
            output = custom_format(data, backend, sort_keys=task.sort_keys)
        else:
            output = backend.dumps(data, sort_keys=task.sort_keys, indent=task.indent)

        # Ensure trailing newline consistency
        formatted_text = output + "\n" if not output.endswith("\n") else output
        has_changed = original_text != formatted_text

        # Compute unified diff if requested
        diff_text: str | None = None
        if task.show_diff and has_changed:
            diff_lines = difflib.unified_diff(
                original_text.splitlines(keepends=True),
                formatted_text.splitlines(keepends=True),
                fromfile=f"a/{task.file_path}",
                tofile=f"b/{task.file_path}",
            )
            diff_text = "".join(diff_lines)

        # Apply changes if not operating in dry-run / check mode
        if has_changed and not task.check_only:
            _atomic_write(file_path, formatted_text, create_backup=task.backup)

        return ProcessResult(
            file_path=task.file_path,
            success=True,
            changed=has_changed,
            diff=diff_text,
        )

    except json.JSONDecodeError as e:
        return ProcessResult(
            file_path=task.file_path,
            success=False,
            changed=False,
            error=f"Invalid JSON at line {e.lineno}, col {e.colno}: {e.msg}",
        )
    except OSError as e:
        return ProcessResult(
            file_path=task.file_path,
            success=False,
            changed=False,
            error=f"I/O error: {e}",
        )
    except Exception as e:
        return ProcessResult(
            file_path=task.file_path,
            success=False,
            changed=False,
            error=f"Unexpected error: {e}",
        )


# =============================================================================
# FILE DISCOVERY & FILTERING
# =============================================================================


def is_json_file(path: Path) -> bool:
    """Determines whether a file is JSON by extension or byte inspection."""
    if path.suffix.lower() in JSON_EXTENSIONS:
        return True
    try:
        with path.open("rb") as f:
            first_char = f.read(1).strip()
            return first_char in (b"{", b"[")
    except OSError:
        return False


def is_excluded(path: Path, exclude_patterns: Sequence[str]) -> bool:
    """Checks if a given path matches any exclusion directory or pattern."""
    for part in path.parts:
        if part in DEFAULT_EXCLUDES:
            return True
    path_str = str(path)
    return any(fnmatch.fnmatch(path_str, pat) or fnmatch.fnmatch(path.name, pat) for pat in exclude_patterns)


def collect_json_files(
    paths: Sequence[str],
    recursive: bool = True,
    exclude_patterns: Sequence[str] = (),
) -> set[Path]:
    """Recursively traverses directories to locate candidate JSON files."""
    found: set[Path] = set()
    glob_pat = "**/*" if recursive else "*"

    for raw in paths:
        p = Path(raw)
        if p.is_file():
            if not is_excluded(p, exclude_patterns):
                found.add(p)
        elif p.is_dir():
            for child in p.glob(glob_pat):
                if child.is_file() and not is_excluded(child, exclude_patterns) and is_json_file(child):
                    found.add(child)

    return found


# =============================================================================
# STDIN / STDOUT PIPELINE HANDLER
# =============================================================================


def process_stdin(args: argparse.Namespace, backend: _Backend) -> int:
    """Processes JSON stream from standard input and writes result to standard output."""
    try:
        input_text = sys.stdin.read()
        if not input_text.strip():
            return 0

        data = backend.loads(input_text)

        if args.minify:
            output = backend.dumps(data, sort_keys=args.sort_keys, compact=True)
        elif args.custom and not args.minify:
            output = custom_format(data, backend, sort_keys=args.sort_keys)
        else:
            output = backend.dumps(data, sort_keys=args.sort_keys, indent=args.indent)

        sys.stdout.write(output + ("\n" if not output.endswith("\n") else ""))
        return 0
    except Exception as e:
        print(f"Error processing standard input: {e}", file=sys.stderr)
        return 1


# =============================================================================
# CLI PARSER BUILDER
# =============================================================================


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fast, multi-backend parallel JSON prettifier, minifier, and linter.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  jb file.json                 # Prettify in-place (2 spaces)
  jb -m file.json              # Minify in-place
  jb --check .                 # Check formatting across directory without writing
  jb --diff file.json          # Print diffs of unformatted files
  cat input.json | jb -m -     # Pipe minified JSON from stdin to stdout
  jb --indent 4 --backup src/  # Format with 4 spaces indent, saving .bak files
  jb --backend orjson dir/     # Explicitly select orjson backend
        """,
    )

    # Formatting Modes
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("-b", "--beautify", action="store_true", help="Beautify JSON (default action)")
    mode_group.add_argument("-m", "--minify", action="store_true", help="Minify JSON (compact output)")

    # Options
    parser.add_argument(
        "-c",
        "--custom",
        action="store_true",
        help="Custom layout: explode top container across lines, keep nested arrays/objects inline.",
    )
    parser.add_argument("-s", "--sort-keys", action="store_true", help="Sort object keys alphabetically")
    parser.add_argument("-i", "--indent", type=int, default=PRETTY_INDENT_DEFAULT, help="Indent level (default: 2)")

    # Execution Modes & CI Integration
    parser.add_argument(
        "--check", action="store_true", help="CI mode: verify formatting without modifying files on disk"
    )
    parser.add_argument("-d", "--diff", action="store_true", help="Show unified diffs for unformatted files")
    parser.add_argument("--backup", action="store_true", help="Create .bak copies before overwriting files")

    # Filters & Backend
    parser.add_argument(
        "--backend",
        choices=["auto", "stdlib", "orjson", "ujson"],
        default="auto",
        help="Select parsing/serialization engine (default: auto)",
    )
    parser.add_argument("-e", "--exclude", action="append", default=[], help="Exclude file or glob pattern")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable detailed per-file output logging")

    # Target Paths
    parser.add_argument("paths", nargs="*", default=None, help="JSON files, directories, or '-' for stdin")
    parser.add_argument(
        "--workers", type=int, default=None, help=f"Parallel process count (default: CPUs = {cpu_count()})"
    )

    return parser


# =============================================================================
# CLI MAIN ENTRYPOINT
# =============================================================================


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    # Resolve backend
    try:
        backend = get_backend(args.backend)
    except Exception as e:
        print(f"Backend Initialization Error: {e}", file=sys.stderr)
        return 1

    # Stdin piping workflow
    if args.paths and args.paths[0] == "-":
        return process_stdin(args, backend)

    paths = args.paths or ["."]
    minify = args.minify
    custom = args.custom and not minify

    if args.custom and minify:
        print("Warning: --custom is ignored when --minify is set.", file=sys.stderr)

    # Collect target files
    json_files = collect_json_files(paths, recursive=True, exclude_patterns=args.exclude)
    if not json_files:
        print("No JSON files found.", file=sys.stderr)
        return 1

    # Construct execution tasks
    tasks = [
        ProcessTask(
            file_path=str(f),
            minify=minify,
            sort_keys=args.sort_keys,
            custom=custom,
            indent=args.indent,
            check_only=args.check or args.diff,
            show_diff=args.diff,
            backup=args.backup,
            backend_name=backend.name,
        )
        for f in sorted(json_files)
    ]

    workers = min(args.workers or cpu_count(), len(tasks))
    workers = max(workers, 1)

    # Status summary banner
    mode_desc = (
        "Checking" if args.check else ("Minifying" if minify else ("Custom-formatting" if custom else "Prettifying"))
    )
    print(f"Engine: {backend.name} | Mode: {mode_desc} | Targets: {len(json_files)} file(s) | Workers: {workers}")

    # Process in parallel worker pool
    with Pool(processes=workers) as pool:
        results: list[ProcessResult] = pool.map(process_json_file, tasks)

    success_count = 0
    changed_count = 0
    error_count = 0

    for res in results:
        if not res.success:
            error_count += 1
            print(f"✗ {res.file_path}: {res.error}", file=sys.stderr)
            continue

        success_count += 1
        if res.changed:
            changed_count += 1

        # Verbose or Diff Output
        if res.diff:
            print(res.diff)
        elif args.verbose:
            status = "would reformat" if args.check else ("reformatted" if res.changed else "unchanged")
            print(f"• {res.file_path}: {status}")

    # Summary report and exit codes
    print("\n--- Summary ---")
    print(f"Processed: {success_count}/{len(tasks)} file(s)")
    if changed_count:
        action_word = "would be modified" if args.check else "modified"
        print(f"Files {action_word}: {changed_count}")
    if error_count:
        print(f"Failed: {error_count} file(s)")

    # CI check failed or runtime errors
    if error_count > 0 or (args.check and changed_count > 0):
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
