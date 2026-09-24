"""
optimize_svgs.py

Optimize ``.svg`` files in place by invoking `svgo <https://github.com/svg/svgo>`_
via :mod:`subprocess`.

The script walks the given paths (or the current directory, recursively, when
none are provided) and dispatches every ``.svg`` file to a pool of 8 worker
processes.  Each worker runs::

    svgo --input <original> --output <temp-in-same-dir> [extra args...]

and then, only if

    * svgo exited with status 0,
    * the produced file exists and is non-empty,
    * the produced file parses as well-formed XML, and
    * the produced file is **strictly smaller** than the input,

atomically renames the temp file over the original with :func:`os.replace`.
Failures — and outputs that are not smaller — never touch the original file.

Design notes
------------
* **Atomicity.** The temp output lives in the same directory as the input, so
  the final rename is atomic on POSIX and on the same volume on Windows.
* **No regression.** If svgo returns an output whose size is greater than or
  equal to the input's, the write is skipped and the original is preserved.
* **Symlinks.** Input paths are resolved with ``Path.resolve()`` before being
  handed to svgo and before the final ``os.replace``, so symlinked SVGs have
  their *target* rewritten rather than being replaced by a regular file.
* **Streaming.** The parent process never reads SVG bytes into memory; svgo
  reads the source file and writes the destination file directly.
* **Lazy discovery.** The pool is fed via a generator
  (:func:`iter_svg_files`), so even enormous trees do not materialise the
  full file list in memory.
* **Reporting.** Both svgo's stdout and stderr are captured and printed by
  the parent process (never by the workers, which would interleave output).

Usage
-----
::

    optimize_svgs.py [-q] [--dry-run] [--multipass] [--pretty]
                     [--svgo PATH] [--svgo-arg ARG]... [--timeout SECONDS]
                     [PATH ...]

Each ``PATH`` may be an ``.svg`` file or a directory (walked recursively).
Duplicates are processed once.  If no ``PATH`` is given, the current directory
is used.

Requires Python 3.12+ and ``svgo`` on ``PATH`` (or supplied with ``--svgo``).
"""

from __future__ import annotations

import argparse
import functools
import multiprocessing as mp
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterator, NamedTuple


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

#: Number of parallel worker processes.  Fixed by design.
NUM_WORKERS = 8

#: Number of tasks handed to a worker at a time.  Small values keep the pool
#: responsive; large values amortise IPC.  4 is a good middle ground.
CHUNKSIZE = 4

#: Default per-file subprocess timeout, in seconds.
DEFAULT_TIMEOUT = 300.0

#: Directories silently pruned during recursive discovery.  Users who really
#: want to process these can pass them explicitly.
SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".tox",
        ".nox",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        "node_modules",
        ".cache",
        ".idea",
        ".vscode",
    }
)


# --------------------------------------------------------------------------- #
# Result record
# --------------------------------------------------------------------------- #


class ProcessResult(NamedTuple):
    """
    Outcome of processing a single ``.svg`` file.

    Attributes
    ----------
    path
        The path that was processed (as originally discovered).
    original_size
        Size of the input file, in bytes.
    new_size
        Size of svgo's output, in bytes.  ``0`` when svgo failed to produce
        usable output.
    stdout, stderr
        Captured streams from svgo (may be empty).
    skipped
        ``True`` if svgo produced valid, usable output that was *not* written
        back because it was not smaller than the input.
    error
        ``None`` on success; a short human-readable message on failure.
    """

    path: Path
    original_size: int
    new_size: int
    stdout: str
    stderr: str
    skipped: bool
    error: str | None


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def _resolve_svgo_binary(explicit: str | None) -> str | None:
    """
    Locate the ``svgo`` executable.

    * When *explicit* is given, it is tried first as a filesystem path and
      then as a name on ``PATH``.
    * Otherwise ``svgo`` is looked up on ``PATH``.
    * Returns ``None`` when nothing usable is found.
    """
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file():
            return str(candidate.resolve())
        return shutil.which(explicit)
    return shutil.which("svgo")


def _human_size(n: int) -> str:
    """Format a byte count for human consumption (e.g. ``12.4 KiB``)."""
    size = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def _indent_print(text: str, *, prefix: str, stream=None) -> None:
    """Print *text* line-by-line, prefixing each line with *prefix*."""
    stream = stream if stream is not None else sys.stdout
    stripped = text.rstrip("\r\n")
    if not stripped:
        return
    for line in stripped.splitlines():
        stream.write(f"{prefix}{line}\n")
    stream.flush()


# --------------------------------------------------------------------------- #
# Per-file worker (top-level so it is picklable)
# --------------------------------------------------------------------------- #


def process_file(
    path: Path,
    *,
    svgo_bin: str,
    extra_args: tuple[str, ...],
    timeout: float,
    dry_run: bool,
) -> ProcessResult:
    """
    Run svgo on a single ``.svg`` file and (optionally) write the result back
    in place.

    The file is *not* modified unless every validation step succeeds **and**
    svgo's output is strictly smaller than the input.  The temp output is
    always cleaned up, whatever the outcome.
    """
    # ---- 1. Resolve symlinks so os.replace() targets the real file. -------- #
    try:
        target = path.resolve(strict=True)
    except OSError:
        target = path

    # ---- 2. Read the original size for reporting / comparison. ------------- #
    try:
        original_size = target.stat().st_size
    except OSError as exc:
        return ProcessResult(path, 0, 0, "", "", False, f"stat error: {exc}")

    # ---- 3. Create a temp file in the target's directory. ------------------ #
    # mkstemp() creates the file with mode 0600 and a unique name; svgo will
    # truncate & overwrite it.  Placing it in the same directory guarantees
    # that os.replace() is a same-filesystem rename (atomic).
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".svg.tmp",
            dir=str(target.parent),
        )
        os.close(fd)
    except OSError as exc:
        return ProcessResult(
            path,
            original_size,
            0,
            "",
            "",
            False,
            f"tempfile error: {exc}",
        )
    tmp_path = Path(tmp_name)

    try:
        # ---- 4. Invoke svgo. ----------------------------------------------- #
        cmd = [
            svgo_bin,
            "--input",
            str(target),
            "--output",
            str(tmp_path),
            *extra_args,
        ]
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ProcessResult(
                path,
                original_size,
                0,
                "",
                "",
                False,
                f"svgo timed out after {timeout:g}s",
            )
        except OSError as exc:
            return ProcessResult(
                path,
                original_size,
                0,
                "",
                "",
                False,
                f"svgo launch failed: {exc}",
            )

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""

        # ---- 5. Validate svgo's exit code. --------------------------------- #
        if completed.returncode != 0:
            return ProcessResult(
                path,
                original_size,
                0,
                stdout,
                stderr,
                False,
                f"svgo exited with code {completed.returncode}",
            )

        # ---- 6. Validate output existence / non-emptiness. ----------------- #
        try:
            if not tmp_path.is_file():
                return ProcessResult(
                    path,
                    original_size,
                    0,
                    stdout,
                    stderr,
                    False,
                    "svgo did not produce an output file",
                )
            new_size = tmp_path.stat().st_size
        except OSError as exc:
            return ProcessResult(
                path,
                original_size,
                0,
                stdout,
                stderr,
                False,
                f"stat on output failed: {exc}",
            )

        if new_size == 0:
            return ProcessResult(
                path,
                original_size,
                0,
                stdout,
                stderr,
                False,
                "svgo produced an empty output file",
            )

        # ---- 7. Validate output is well-formed XML. ------------------------ #
        try:
            ET.parse(tmp_path)
        except ET.ParseError as exc:
            return ProcessResult(
                path,
                original_size,
                new_size,
                stdout,
                stderr,
                False,
                f"invalid XML in svgo output: {exc}",
            )
        except OSError as exc:
            return ProcessResult(
                path,
                original_size,
                new_size,
                stdout,
                stderr,
                False,
                f"cannot re-read svgo output: {exc}",
            )

        # ---- 8. Skip if the output is not strictly smaller. ---------------- #
        # This covers both "bigger" and "same size": writing back an equal-
        # size file gains nothing and churns mtime/inode.
        if new_size >= original_size:
            return ProcessResult(
                path,
                original_size,
                new_size,
                stdout,
                stderr,
                skipped=True,
                error=None,
            )

        # ---- 9. Optionally skip the write (dry-run). ----------------------- #
        if dry_run:
            return ProcessResult(
                path,
                original_size,
                new_size,
                stdout,
                stderr,
                skipped=False,
                error=None,
            )

        # ---- 10. Preserve the original file mode. -------------------------- #
        try:
            mode = target.stat().st_mode
        except OSError:
            mode = None
        if mode is not None:
            try:
                os.chmod(tmp_path, mode)
            except OSError:
                pass

        # ---- 11. Atomic swap. ---------------------------------------------- #
        try:
            os.replace(tmp_path, target)
        except OSError as exc:
            return ProcessResult(
                path,
                original_size,
                new_size,
                stdout,
                stderr,
                False,
                f"atomic replace failed: {exc}",
            )

        return ProcessResult(
            path,
            original_size,
            new_size,
            stdout,
            stderr,
            skipped=False,
            error=None,
        )

    finally:
        # On success, os.replace moved the file away; on any other path, this
        # removes the leftover temp file.  Never let cleanup mask the real
        # result.
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# Path discovery
# --------------------------------------------------------------------------- #


def iter_svg_files(roots: Iterator[Path] | list[Path]) -> Iterator[Path]:
    """
    Yield unique ``.svg`` files reachable from *roots*.

    * A file argument is yielded directly (if it has a ``.svg`` suffix).
    * A directory argument is walked recursively with :meth:`Path.walk`
      (Python 3.12+), pruning any directory in :data:`SKIP_DIRS`.
    * Duplicate paths (e.g. a file also discovered via a directory argument)
      are yielded only once.
    * The generator is lazy, so the multiprocessing feeder thread can stream
      tasks to workers without ever materialising the whole tree.
    """
    seen: set[Path] = set()

    def _on_walk_error(exc: OSError) -> None:
        print(f"warning: {exc}", file=sys.stderr)

    for root in roots:
        try:
            if root.is_file():
                if root.suffix.lower() == ".svg":
                    try:
                        key = root.resolve()
                    except OSError:
                        key = root
                    if key not in seen:
                        seen.add(key)
                        yield root

            elif root.is_dir():
                for dirpath, dirnames, filenames in root.walk(on_error=_on_walk_error):
                    # Prune in place — Path.walk() honours this mutation.
                    dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
                    for name in filenames:
                        if not name.lower().endswith(".svg"):
                            continue
                        candidate = dirpath / name
                        try:
                            key = candidate.resolve()
                        except OSError:
                            continue
                        if key in seen:
                            continue
                        seen.add(key)
                        yield candidate
            else:
                print(
                    f"warning: skipping non-existent path: {root}",
                    file=sys.stderr,
                )
        except OSError as exc:
            print(
                f"warning: cannot access {root}: {exc}",
                file=sys.stderr,
            )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="optimize_svgs",
        description=(
            "Optimize .svg files in place by invoking svgo. Files are "
            "written back atomically and only if svgo's output is "
            "well-formed XML and strictly smaller than the input."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        metavar="PATH",
        help=("Files or directories to process. Defaults to the current directory, walked recursively."),
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Do not print svgo's own stdout/stderr (only our summary lines).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run svgo and validate its output, but do not modify any files.",
    )
    parser.add_argument(
        "--multipass",
        action="store_true",
        help="Pass --multipass to svgo (run the optimizer repeatedly until no further gain).",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pass --pretty to svgo (pretty-print the output).",
    )
    parser.add_argument(
        "--svgo",
        metavar="PATH",
        default=None,
        help="Path to the svgo executable (default: search PATH).",
    )
    parser.add_argument(
        "--svgo-arg",
        metavar="ARG",
        action="append",
        default=[],
        help="Extra argument to pass to svgo; may be repeated.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        metavar="SECONDS",
        help=f"Per-file svgo timeout (default: {DEFAULT_TIMEOUT:g}s).",
    )
    return parser


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # ---- Locate svgo. ----------------------------------------------------- #
    svgo_bin = _resolve_svgo_binary(args.svgo)
    if svgo_bin is None:
        print(
            "error: could not find svgo. Install it (`npm i -g svgo`) or pass --svgo PATH.",
            file=sys.stderr,
        )
        return 1

    # ---- Assemble extra svgo arguments. ----------------------------------- #
    extra_args: list[str] = list(args.svgo_arg)
    if args.multipass:
        extra_args.append("--multipass")
    if args.pretty:
        extra_args.append("--pretty")
    extra_args_tuple: tuple[str, ...] = tuple(extra_args)

    # ---- Bind options into a single-argument callable for the pool. ------- #
    # functools.partial is picklable on all platforms (spawn included).
    worker = functools.partial(
        process_file,
        svgo_bin=svgo_bin,
        extra_args=extra_args_tuple,
        timeout=args.timeout,
        dry_run=args.dry_run,
    )

    roots: list[Path] = args.paths or [Path.cwd()]

    # ---- Run the pool. ---------------------------------------------------- #
    total = 0
    changed = 0
    unchanged = 0
    skipped = 0
    errors = 0
    total_before = 0
    total_after = 0

    with mp.Pool(processes=NUM_WORKERS) as pool:
        results = pool.imap_unordered(
            worker,
            iter_svg_files(roots),
            chunksize=CHUNKSIZE,
        )
        for result in results:
            total += 1
            path = result.path

            if result.error is not None:
                errors += 1
                print(f"ERROR  {path}: {result.error}", file=sys.stderr)
                if not args.quiet:
                    if result.stdout.strip():
                        _indent_print(result.stdout, prefix="  stdout | ")
                    if result.stderr.strip():
                        _indent_print(
                            result.stderr,
                            prefix="  stderr | ",
                            stream=sys.stderr,
                        )
                continue

            total_before += result.original_size
            total_after += result.new_size

            saved = result.original_size - result.new_size
            pct = (saved / result.original_size * 100.0) if result.original_size else 0.0

            # ---- Categorise the outcome for reporting. -------------------- #
            if result.skipped:
                skipped += 1
                tag = "SKIP   "
                note = "  (output not smaller; original kept)"
            elif result.new_size == result.original_size:
                unchanged += 1
                tag = "SAME   "
                note = ""
            else:
                changed += 1
                tag = "DRY-RUN " if args.dry_run else "OK     "
                note = ""

            print(
                f"{tag}{path}: "
                f"{_human_size(result.original_size)} -> "
                f"{_human_size(result.new_size)} "
                f"({pct:+.1f}%){note}"
            )

            if not args.quiet:
                if result.stdout.strip():
                    _indent_print(result.stdout, prefix="  | ")
                if result.stderr.strip():
                    _indent_print(result.stderr, prefix="  ! ", stream=sys.stderr)

    # ---- Summary. --------------------------------------------------------- #
    if total == 0:
        print("No .svg files found.", file=sys.stderr)
        return 1

    total_saved = total_before - total_after
    total_pct = (total_saved / total_before * 100.0) if total_before else 0.0
    verb = "would have saved" if args.dry_run else "saved"

    summary = (
        f"\nProcessed {total} file(s): "
        f"{changed} changed, {unchanged} unchanged, "
        f"{skipped} skipped (larger), {errors} error(s).\n"
        f"Total size: {_human_size(total_before)} -> "
        f"{_human_size(total_after)} "
        f"(filtered {verb} {_human_size(total_saved)}, {total_pct:.1f}%)."
    )
    print(summary, file=sys.stderr if errors else sys.stdout)

    return 2 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
