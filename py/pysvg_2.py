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

NUM_WORKERS = 8

CHUNKSIZE = 4

DEFAULT_TIMEOUT = 300.0

SKIP_DIRS: frozenset[str] = frozenset({
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
})


class ProcessResult(NamedTuple):
    path: Path
    original_size: int
    new_size: int
    stdout: str
    stderr: str
    skipped: bool
    error: str | None


def _resolve_svgo_binary(explicit: str | None) -> str | None:
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file():
            return str(candidate.resolve())
        return shutil.which(explicit)
    return shutil.which("svgo")


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def _indent_print(text: str, *, prefix: str, stream=None) -> None:
    stream = stream if stream is not None else sys.stdout
    stripped = text.rstrip("\r\n")
    if not stripped:
        return
    for line in stripped.splitlines():
        stream.write(f"{prefix}{line}\n")
    stream.flush()


def process_file(
    path: Path,
    *,
    svgo_bin: str,
    extra_args: tuple[str, ...],
    timeout: float,
    dry_run: bool,
) -> ProcessResult:

    try:
        target = path.resolve(strict=True)
    except OSError:
        target = path

    try:
        original_size = target.stat().st_size
    except OSError as exc:
        return ProcessResult(path, 0, 0, "", "", False, f"stat error: {exc}")

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

        try:
            mode = target.stat().st_mode
        except OSError:
            mode = None
        if mode is not None:
            try:
                os.chmod(tmp_path, mode)
            except OSError:
                pass

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
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def iter_svg_files(roots: Iterator[Path] | list[Path]) -> Iterator[Path]:
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    svgo_bin = _resolve_svgo_binary(args.svgo)
    if svgo_bin is None:
        print(
            "error: could not find svgo. Install it (`npm i -g svgo`) or pass --svgo PATH.",
            file=sys.stderr,
        )
        return 1

    extra_args: list[str] = list(args.svgo_arg)
    if args.multipass:
        extra_args.append("--multipass")
    if args.pretty:
        extra_args.append("--pretty")
    extra_args_tuple: tuple[str, ...] = tuple(extra_args)

    worker = functools.partial(
        process_file,
        svgo_bin=svgo_bin,
        extra_args=extra_args_tuple,
        timeout=args.timeout,
        dry_run=args.dry_run,
    )

    roots: list[Path] = args.paths or [Path.cwd()]

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
