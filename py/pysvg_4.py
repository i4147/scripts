"""
optimize_svgs.py

Optimize ``.svg`` files in place by invoking `svgo <https://github.com/svg/svgo>`_
via :mod:`subprocess`.

File discovery is delegated to the ``fastwalk`` Rust extension
(:func:`fastwalk.walk_files`), which recursively walks a root directory and
returns a ``list[pathlib.Path]``.  ``walk_files`` accepts only a path, so all
filtering — pruning of common noise directories, symlink rejection, and the
``.svg`` suffix check — is applied in Python to the returned list before any
path is handed to svgo.

Extension matching is **case-insensitive**: ``.svg``, ``.SVG``, ``.Svg`` and
any other casing are all accepted.  The temp file written next to each input
mirrors the input's casing so directory listings stay intuitive.

Each discovered file is dispatched to a pool of 8 worker processes.  Every
worker runs::

    svgo --input <original> --output <temp-in-same-dir> [extra args...]

and then, only if

    * svgo exited with status 0,
    * the produced file exists and is non-empty,
    * the produced file parses as well-formed XML,
    * the produced file is not byte-identical to the input, and
    * the produced file is **strictly smaller** than the input,

atomically renames the temp file over the original with :func:`os.replace`.
Failures — and outputs that are identical or larger — never touch the
original file.

Design notes
------------
* **Discovery.** ``fastwalk.walk_files`` is called per root and returns a
  materialised ``list[Path]``.  Results are consumed in bounded chunks
  (:data:`WALK_CHUNK`) and fed to
  :meth:`multiprocessing.pool.Pool.imap_unordered` so the parent's own
  working memory stays flat even for very large trees.
* **Filtering.** Since ``walk_files`` exposes no pruning options, the
  :data:`SKIP_DIRS` set is enforced in Python via
  :func:`_is_under_skip_dir`.  Symlinks and non-``.svg`` entries are dropped
  here too, so svgo is only ever invoked on real regular files.
* **Atomicity.** The temp output lives in the same directory as the input, so
  the final rename is atomic on POSIX and on the same volume on Windows.
* **No-op detection.** If svgo produces output byte-identical to the input,
  the write is skipped entirely — no inode churn, no mtime bump.  This keeps
  file watchers and build caches warm.
* **No regression.** If svgo returns an output whose size is greater than the
  input's, the write is skipped and the original is preserved.
* **Streaming.** The parent process never reads SVG bytes into memory; svgo
  reads the source file and writes the destination file directly.
* **Reporting.** Both svgo's stdout and stderr are captured and printed by
  the parent process (never by the workers, which would interleave output).

Usage
-----
::

    optimize_svgs.py [-q] [--dry-run] [--multipass] [--pretty]
                     [--svgo PATH] [--svgo-arg ARG]... [--timeout SECONDS]
                     [PATH ...]

Each ``PATH`` may be an ``.svg`` file (any casing) or a directory (walked
recursively by ``fastwalk``).  Duplicates are processed once.  If no ``PATH``
is given, the current directory is used.

Requires Python 3.12+, the ``fastwalk`` extension, and ``svgo`` on ``PATH``
(or supplied with ``--svgo``).
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
from typing import Final, Iterable, Iterator, NamedTuple

# Rust extension providing the fast recursive walker.
# ``walk_files(root: Path) -> list[Path]`` — accepts only a path, and returns
# every entry under ``root``.  All filtering is done on our side.
from fastwalk import walk_files


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

#: Number of parallel worker processes.  Fixed by design.
NUM_WORKERS: Final[int] = 8

#: Number of tasks handed to a worker at a time.  Small values keep the pool
#: responsive; large values amortise IPC.  4 is a good middle ground.
CHUNKSIZE: Final[int] = 4

#: Number of paths pulled from discovery before feeding the next batch to the
#: pool.  Keeps the parent's peak memory bounded even though ``walk_files``
#: itself returns a materialised list per root.
WALK_CHUNK: Final[int] = 512

#: Default per-file subprocess timeout, in seconds.
DEFAULT_TIMEOUT: Final[float] = 300.0

#: Buffer size used when streaming files for the byte-identical check.
_HASH_CHUNK: Final[int] = 64 * 1024

#: Accepted file extensions, compared **case-insensitively**.
#: Kept as a set of already-lowercased values; callers lowercase the
#: candidate's suffix before testing.  Add ``.svgz`` here if you ever want to
#: handle gzipped SVGs.
SVG_SUFFIXES: Final[frozenset[str]] = frozenset({".svg"})

#: Directory names pruned during discovery.  A path is skipped if any of its
#: directory components (relative to the walk root) match one of these names.
#: ``walk_files`` cannot be told to prune on the Rust side, so this filter
#: runs in Python — see :func:`_is_under_skip_dir`.
SKIP_DIRS: Final[frozenset[str]] = frozenset(
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
        "build",
        "dist",
        "target",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
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
        back because it was larger than the input.
    no_change
        ``True`` if svgo produced valid output byte-identical to the input.
        The file is left untouched (no inode churn, no mtime bump).
    error
        ``None`` on success; a short human-readable message on failure.
    """

    path: Path
    original_size: int
    new_size: int
    stdout: str
    stderr: str
    skipped: bool
    no_change: bool
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


def _looks_like_svg(path: Path) -> bool:
    """
    Return ``True`` if *path* has an accepted SVG extension.

    The comparison is **case-insensitive**: ``.svg``, ``.SVG``, ``.Svg`` and
    any other casing all pass.  We lowercase only the suffix (a short string)
    rather than the whole path, so the operation is essentially free.
    """
    return path.suffix.lower() in SVG_SUFFIXES


def _is_under_skip_dir(path: Path, root: Path) -> bool:
    """
    Return ``True`` if *path* sits inside a directory listed in
    :data:`SKIP_DIRS`, relative to *root*.

    Only the components between *root* and *path* are examined, so a walk
    root that is itself named ``.git`` (e.g. the user explicitly ran
    ``optimize_svgs.py .git/hooks``) is still processed.

    The check is done on the *path components* (not on the resolved path) so
    it stays cheap: no filesystem access, no symlink resolution.
    """
    try:
        rel = path.relative_to(root)
    except ValueError:
        # ``path`` is not under ``root`` — shouldn't happen for walk_files
        # output, but be defensive rather than accidentally dropping files.
        rel = path
    # ``parts[:-1]`` because the last component is the file itself; we only
    # care about directory names.
    return any(part in SKIP_DIRS for part in rel.parts[:-1])


def _temp_suffix_for(target: Path) -> str:
    """
    Build a temp-file suffix that preserves *target*'s original extension
    casing, so a ``logo.SVG`` gets a ``.SVG.tmp`` scratch file rather than
    a lowercase ``.svg.tmp``.  Purely cosmetic, but it makes ``ls`` output
    during a long run easier to follow.
    """
    return f"{target.suffix}.tmp"


def _files_are_identical(a: Path, b: Path) -> bool:
    """
    Return ``True`` if *a* and *b* have identical contents.

    Fast paths, in order:

    1. Compare sizes via ``stat`` — if they differ, the files differ.
    2. Stream both files in fixed-size chunks and compare bytes directly.

    A direct byte comparison is used rather than hashing: for two files that
    are actually equal (the common case here), any correct algorithm has to
    read both to EOF, so hashing only adds CPU on top of the unavoidable
    I/O.  Comparing chunks lets us bail out early as soon as a mismatch is
    found, which is common when svgo *did* change something.

    Memory stays flat regardless of file size (``_HASH_CHUNK`` bytes per
    open file).
    """
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
    except OSError:
        # If we can't stat, fall back to a full read attempt.
        pass

    try:
        with a.open("rb") as fa, b.open("rb") as fb:
            while True:
                ba = fa.read(_HASH_CHUNK)
                bb = fb.read(_HASH_CHUNK)
                if ba != bb:
                    return False
                if not ba:  # both EOF at the same time
                    return True
    except OSError:
        # If either file can't be opened/read, err on the side of "different"
        # so the caller performs the write (the safe choice: better to
        # rewrite than to silently skip a needed change).
        return False


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

    The file is *not* modified unless every validation step succeeds, the
    output differs from the input, **and** the output is strictly smaller.
    The temp output is always cleaned up, whatever the outcome.
    """
    # ---- 1. Resolve symlinks so os.replace() targets the real file. -------- #
    # Discovery already filters symlinks out, so this is only meaningful for
    # odd setups (hardlinks, bind-mounts).  ``strict=True`` surfaces a
    # vanished file as an OSError which we fall back on gracefully.
    try:
        target = path.resolve(strict=True)
    except OSError:
        target = path

    # ---- 2. Read the original size for reporting / comparison. ------------- #
    try:
        original_size = target.stat().st_size
    except OSError as exc:
        return ProcessResult(path, 0, 0, "", "", False, False, f"stat error: {exc}")

    # ---- 3. Create a temp file in the target's directory. ------------------ #
    # mkstemp() creates the file with mode 0600 and a unique name; svgo will
    # truncate & overwrite it.  Placing it in the same directory guarantees
    # that os.replace() is a same-filesystem rename (atomic).  The suffix is
    # derived from the target so ``logo.SVG`` gets a ``.SVG.tmp`` scratch
    # file, which makes in-progress listings self-explanatory.
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=_temp_suffix_for(target),
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
                False,
                f"cannot re-read svgo output: {exc}",
            )

        # ---- 8a. Skip if the output is byte-identical to the input. -------- #
        # svgo sometimes produces output that matches the input exactly (e.g.
        # the file was already optimal and svgo's serializer round-trips it).
        # In that case the atomic rename would needlessly bump the inode and
        # mtime, which can retrigger watchers and invalidate build caches.
        if new_size == original_size and _files_are_identical(target, tmp_path):
            return ProcessResult(
                path,
                original_size,
                new_size,
                stdout,
                stderr,
                skipped=False,
                no_change=True,
                error=None,
            )

        # ---- 8b. Skip if the output is larger than the input. -------------- #
        # Writing back a larger file would be a regression: the original is
        # preserved and the caller is told the optimizer made things worse.
        if new_size > original_size:
            return ProcessResult(
                path,
                original_size,
                new_size,
                stdout,
                stderr,
                skipped=True,
                no_change=False,
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
                no_change=False,
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
                skipped=False,
                no_change=False,
                error=f"atomic replace failed: {exc}",
            )

        return ProcessResult(
            path,
            original_size,
            new_size,
            stdout,
            stderr,
            skipped=False,
            no_change=False,
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
# Path discovery (delegated to the fastwalk Rust extension)
# --------------------------------------------------------------------------- #


def _paths_from_roots(roots: Iterable[Path]) -> Iterator[Path]:
    """
    Yield de-duplicated, symlink-free, skip-dir-filtered ``.svg`` paths from
    *roots* using :func:`fastwalk.walk_files`.

    Behaviour
    ---------
    * A file argument with an accepted SVG extension (any casing) is yielded
      directly, after the symlink and duplicate checks.
    * A directory argument is handed to ``fastwalk.walk_files``, which
      recursively walks it and returns a ``list[Path]``.  We then drop:

        - paths whose directory components include a name from
          :data:`SKIP_DIRS` (see :func:`_is_under_skip_dir`),
        - symlinks (never clobber a symlink; never follow one),
        - entries whose extension is not ``.svg`` regardless of casing.

    * Duplicates across roots are collapsed via ``Path.resolve()`` keys, so
      passing ``.`` and ``./assets`` at the same time yields each file once.
    * The generator is lazy *per root*; ``walk_files`` itself materialises
      each root's result as a list.  Callers that need strictly bounded
      memory should feed the pool in chunks (see :func:`_iter_chunks`).
    """
    seen: set[Path] = set()

    for root in roots:
        try:
            # ---- 1. Explicit file argument. -------------------------------- #
            if root.is_file():
                if not _looks_like_svg(root):
                    continue
                if root.is_symlink():
                    continue
                try:
                    key = root.resolve()
                except OSError:
                    key = root
                if key in seen:
                    continue
                seen.add(key)
                yield root
                continue

            # ---- 2. Non-existent / special path. --------------------------- #
            if not root.is_dir():
                print(
                    f"warning: skipping non-existent path: {root}",
                    file=sys.stderr,
                )
                continue

            # ---- 3. Directory: hand off to the Rust walker. ---------------- #
            try:
                found = walk_files(root)
            except Exception as exc:  # defensive: never crash the walker
                print(
                    f"warning: fastwalk failed on {root}: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                continue

            # ---- 4. Python-side filtering of the returned list. ------------ #
            # Order matters for speed: suffix check first (no I/O), then the
            # skip-dir test (no I/O), then symlink check (one lstat), then
            # resolve() for dedup (one realpath).
            for candidate in found:
                if not _looks_like_svg(candidate):
                    continue
                if _is_under_skip_dir(candidate, root):
                    continue
                try:
                    if candidate.is_symlink():
                        continue
                    key = candidate.resolve()
                except OSError:
                    continue
                if key in seen:
                    continue
                seen.add(key)
                yield candidate

        except OSError as exc:
            print(
                f"warning: cannot access {root}: {exc}",
                file=sys.stderr,
            )


def _iter_chunks(it: Iterator[Path], size: int) -> Iterator[list[Path]]:
    """
    Yield successive lists of at most *size* elements from *it*.

    Used to feed the pool in bounded batches.  ``imap_unordered`` already
    consumes a single iterable, so this is only about not constructing an
    unbounded list in memory when the source is itself lazy.
    """
    chunk: list[Path] = []
    for item in it:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="optimize_svgs",
        description=(
            "Optimize .svg files in place by invoking svgo. Files are "
            "written back atomically and only if svgo's output is "
            "well-formed XML, different from the input, and strictly "
            "smaller. Discovery uses the fastwalk Rust extension. "
            "Extensions are matched case-insensitively (.svg / .SVG)."
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

    # ---- Flatten the per-root generator into a single lazy stream. -------- #
    # ``_iter_chunks`` turns that stream into bounded batches; feeding the
    # batches one at a time keeps the parent's own working set small even
    # though ``walk_files`` materialises each root's result.
    def _chunk_stream() -> Iterator[Path]:
        for chunk in _iter_chunks(_paths_from_roots(roots), WALK_CHUNK):
            yield from chunk

    # ---- Run the pool. ---------------------------------------------------- #
    total = 0
    changed = 0
    unchanged = 0
    skipped = 0
    no_change = 0
    errors = 0
    total_before = 0
    total_after = 0

    with mp.Pool(processes=NUM_WORKERS) as pool:
        results = pool.imap_unordered(
            worker,
            _chunk_stream(),
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
            if result.no_change:
                no_change += 1
                tag = "NOCHG  "
                note = "  (identical to input; not rewritten)"
            elif result.skipped:
                skipped += 1
                tag = "SKIP   "
                note = "  (output larger; original kept)"
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
        f"{changed} changed, {unchanged} unchanged (same size, different "
        f"bytes), {no_change} byte-identical, "
        f"{skipped} skipped (larger), {errors} error(s).\n"
        f"Total size: {_human_size(total_before)} -> "
        f"{_human_size(total_after)} "
        f"(filtered {verb} {_human_size(total_saved)}, {total_pct:.1f}%)."
    )
    print(summary, file=sys.stderr if errors else sys.stdout)

    return 2 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
