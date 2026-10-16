#!/data/data/com.termux/files/usr/bin/env python

from __future__ import annotations
import argparse
import contextlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from functools import partial
from multiprocessing import Pool
from pathlib import Path
from typing import Final, Iterator, NamedTuple, Sequence
from dh import SKIP_DIRS
from fastwalk import walk_files

cwd = Path.cwd().resolve()
JPEG_SUFFIXES: Final[frozenset[str]] = frozenset({".jpeg", ".jpg"})
JPEG_MAGIC: Final[bytes] = b"\xff\xd8\xff"
WALK_CHUNK: Final[int] = 512
DEFAULT_WORKERS: Final[int] = 8
IMAP_CHUNKSIZE: Final[int] = 4
DEFAULT_TIMEOUT: Final[float] = 300.0
COMPARE_CHUNK: Final[int] = 1 << 16
JPEGOPTIM_SUCCESS: Final[int] = 0
QUALITY_RANGE: Final[range] = range(101)


class ProcessResult(NamedTuple):
    path: Path
    original_size: int
    new_size: int
    stdout: str
    stderr: str
    skipped: bool
    no_change: bool
    error: str | None


def format_bytes(n: int) -> str:
    sign = "-" if n < 0 else ""
    value = float(abs(n))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024.0 or unit == "TiB":
            if unit == "B":
                return f"{sign}{int(value)} B"
            return f"{sign}{value:.2f} {unit}"
        value /= 1024.0
    return f"{sign}{value:.2f} TiB"


def _dedupe(path: Path, seen: set[Path]) -> bool:
    try:
        key = path.resolve()
    except OSError:
        key = path
    if key in seen:
        return False
    seen.add(key)
    return True


def _iter_directory(root: Path, seen: set[Path]) -> Iterator[Path]:
    try:
        found = walk_files(str(root))
    except Exception as exc:
        print(f"warning: walk_files failed for {root}: {exc}", file=sys.stderr)
        return
    for start in range(0, len(found), WALK_CHUNK):
        for entry in found[start : start + WALK_CHUNK]:
            path = Path(entry)
            if path.suffix.lower() not in JPEG_SUFFIXES:
                continue
            try:
                rel = path.relative_to(root)
            except ValueError:
                rel = path
            if any(part in SKIP_DIRS for part in rel.parts[:-1]):
                continue
            try:
                if path.is_symlink():
                    continue
            except OSError:
                continue
            if not _dedupe(path, seen):
                continue
            yield path


def iter_jpeg_files(roots: Sequence[Path]) -> Iterator[Path]:
    seen: set[Path] = set()
    for raw_root in roots:
        try:
            if not raw_root.exists():
                print(
                    f"warning: path does not exist: {raw_root}",
                    file=sys.stderr,
                )
                continue
            if raw_root.is_file():
                if raw_root.is_symlink():
                    print(
                        f"warning: skipping symlink: {raw_root}",
                        file=sys.stderr,
                    )
                    continue
                if raw_root.suffix.lower() in JPEG_SUFFIXES and _dedupe(raw_root, seen):
                    yield raw_root
                continue
            if raw_root.is_dir():
                try:
                    root = raw_root.resolve()
                except OSError as exc:
                    print(
                        f"warning: cannot resolve {raw_root}: {exc}",
                        file=sys.stderr,
                    )
                    continue
                yield from _iter_directory(root, seen)
                continue
            print(
                f"warning: not a file or directory: {raw_root}",
                file=sys.stderr,
            )
        except OSError as exc:
            print(
                f"warning: cannot inspect {raw_root}: {exc}",
                file=sys.stderr,
            )


def _files_identical(a: Path, b: Path, a_size: int, b_size: int) -> bool:
    if a_size != b_size:
        return False
    with a.open("rb") as fa, b.open("rb") as fb:
        while True:
            chunk_a = fa.read(COMPARE_CHUNK)
            chunk_b = fb.read(COMPARE_CHUNK)
            if chunk_a != chunk_b:
                return False
            if not chunk_a:
                return True


def _is_valid_jpeg(path: Path) -> tuple[bool, str | None]:
    try:
        with path.open("rb") as f:
            header = f.read(len(JPEG_MAGIC))
    except OSError as exc:
        return False, f"cannot read output: {exc}"
    if header != JPEG_MAGIC:
        return False, "output is not a JPEG (bad signature)"
    return True, None


def process_file(
    path: Path,
    *,
    jpegoptim: str,
    max_quality: int | None,
    strip: bool,
    progressive: bool,
    normal: bool,
    extra_args: Sequence[str],
    timeout: float,
    dry_run: bool,
) -> ProcessResult:
    try:
        target = path.resolve(strict=True)
    except OSError as exc:
        return ProcessResult(path, 0, 0, "", "", False, False, f"cannot resolve: {exc}")
    try:
        st = target.stat()
    except OSError as exc:
        return ProcessResult(path, 0, 0, "", "", False, False, f"cannot stat: {exc}")
    original_size = st.st_size
    original_mode = stat.S_IMODE(st.st_mode)
    tmp_path: Path | None = None
    try:
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=target.stem + ".",
                suffix=target.suffix + ".tmp",
                dir=str(target.parent),
            )
            with contextlib.suppress(OSError):
                os.close(fd)
            tmp_path = Path(tmp_name)
        except OSError as exc:
            return ProcessResult(
                path,
                original_size,
                0,
                "",
                "",
                False,
                False,
                f"cannot create temp file: {exc}",
            )
        try:
            shutil.copy2(target, tmp_path)
        except OSError as exc:
            return ProcessResult(
                path,
                original_size,
                0,
                "",
                "",
                False,
                False,
                f"cannot stage temp copy: {exc}",
            )
        cmd: list[str] = [jpegoptim]
        if max_quality is not None:
            cmd += ["-m", str(max_quality)]
        if strip:
            cmd.append("--strip-all")
        if progressive and not normal:
            cmd.append("--all-progressive")
        if normal and not progressive:
            cmd.append("--all-normal")
        cmd.extend(extra_args)
        cmd.append("--")
        cmd.append(str(tmp_path))
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
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
                f"jpegoptim timed out after {timeout:g}s",
            )
        except FileNotFoundError:
            return ProcessResult(
                path,
                original_size,
                0,
                "",
                "",
                False,
                False,
                f"jpegoptim executable not found: {jpegoptim!r}",
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
                f"failed to run jpegoptim: {exc}",
            )
        stdout = completed.stdout.decode("utf-8", errors="replace")
        stderr = completed.stderr.decode("utf-8", errors="replace")
        if completed.returncode != JPEGOPTIM_SUCCESS:
            return ProcessResult(
                path,
                original_size,
                0,
                stdout,
                stderr,
                False,
                False,
                f"jpegoptim exited with status {completed.returncode}",
            )
        try:
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
                f"jpegoptim produced no output: {exc}",
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
                "jpegoptim produced an empty file",
            )
        ok, sig_err = _is_valid_jpeg(tmp_path)
        if not ok:
            return ProcessResult(
                path,
                original_size,
                new_size,
                stdout,
                stderr,
                False,
                False,
                sig_err,
            )
        try:
            identical = _files_identical(target, tmp_path, original_size, new_size)
        except OSError as exc:
            return ProcessResult(
                path,
                original_size,
                new_size,
                stdout,
                stderr,
                False,
                False,
                f"cannot compare files: {exc}",
            )
        if identical:
            return ProcessResult(
                path,
                original_size,
                original_size,
                stdout,
                stderr,
                False,
                True,
                None,
            )
        if new_size > original_size:
            return ProcessResult(
                path,
                original_size,
                new_size,
                stdout,
                stderr,
                True,
                False,
                None,
            )
        if new_size == original_size:
            return ProcessResult(
                path,
                original_size,
                new_size,
                stdout,
                stderr,
                True,
                False,
                None,
            )
        if dry_run:
            return ProcessResult(
                path,
                original_size,
                new_size,
                stdout,
                stderr,
                False,
                False,
                None,
            )
        try:
            os.chmod(tmp_path, original_mode)
            os.replace(tmp_path, target)
        except OSError as exc:
            return ProcessResult(
                path,
                original_size,
                new_size,
                stdout,
                stderr,
                False,
                False,
                f"failed to replace original: {exc}",
            )
        tmp_path = None
        return ProcessResult(
            path,
            original_size,
            new_size,
            stdout,
            stderr,
            False,
            False,
            None,
        )
    finally:
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                tmp_path.unlink()


def _classify(result: ProcessResult, dry_run: bool) -> str:
    if result.error is not None:
        return "ERROR"
    if result.no_change:
        return "NOCHG"
    if result.skipped:
        return "SAME" if result.new_size == result.original_size else "SKIP"
    if dry_run:
        return "DRY-RUN"
    return "OK"


def _emit_jpegoptim_output(result: ProcessResult) -> None:
    if result.stdout:
        sys.stdout.write(result.stdout)
        if not result.stdout.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
    if result.stderr:
        sys.stderr.write(result.stderr)
        if not result.stderr.endswith("\n"):
            sys.stderr.write("\n")
        sys.stderr.flush()


def _print_status(result: ProcessResult, tag: str) -> None:
    path = result.path
    orig = result.original_size
    new = result.new_size
    if tag == "OK":
        saved = orig - new
        pct = (saved / orig * 100.0) if orig else 0.0
        print(
            f"[OK]      {path.resolve().relative_to(cwd)}  "
            f"{format_bytes(orig)} -> {format_bytes(new)}  "
            f"(-{format_bytes(saved)}, -{pct:.1f}%)"
        )
    elif tag == "DRY-RUN":
        saved = orig - new
        pct = (saved / orig * 100.0) if orig else 0.0
        print(
            f"[DRY-RUN] {path.resolve().relative_to(cwd)}  "
            f"{format_bytes(orig)} -> {format_bytes(new)}  "
            f"(would save {format_bytes(saved)}, {pct:.1f}%)"
        )
    elif tag == "NOCHG":
        print(f"[NOCHG]   {path.resolve().relative_to(cwd)}  {format_bytes(orig)}  (byte-identical)")
    elif tag == "SAME":
        print(f"[SAME]    {path.resolve().relative_to(cwd)}  {format_bytes(orig)}  (same size, different bytes)")
    elif tag == "SKIP":
        growth = new - orig
        print(
            f"[SKIP]    {path.resolve().relative_to(cwd)}  "
            f"{format_bytes(orig)} -> {format_bytes(new)}  "
            f"(larger by {format_bytes(growth)})"
        )
    else:
        print(
            f"[ERROR]   {path.resolve().relative_to(cwd)}  {result.error}",
            file=sys.stderr,
        )


def _print_summary(counters: dict[str, int], total_before: int, total_after: int) -> None:
    total = sum(counters.values())
    skipped = counters["SAME"] + counters["SKIP"]
    print()
    print("-" * 66)
    print("Summary")
    print("-" * 66)
    print(f"  Processed : {total}")
    print(f"  Changed   : {counters['OK']}")
    if counters["DRY-RUN"]:
        print(f"  Dry-run   : {counters['DRY-RUN']}")
    print(f"  Unchanged : {counters['NOCHG']}")
    print(f"  Skipped   : {skipped}")
    if skipped:
        print(f"      same-size-different-bytes : {counters['SAME']}")
        print(f"      larger-output             : {counters['SKIP']}")
    print(f"  Errored   : {counters['ERROR']}")
    if total_before:
        saved = total_before - total_after
        pct = (saved / total_before * 100.0) if total_before else 0.0
        print()
        print(
            f"  Bytes     : {format_bytes(total_before)} -> "
            f"{format_bytes(total_after)}  "
            f"(saved {format_bytes(saved)}, {pct:.1f}%)"
        )
    else:
        print()
        print("  Bytes     : no size changes")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jpegoptim-optimize",
        description=(
            "Optimize .jpeg / .jpg files in place using jpegoptim. "
            "With no paths, the current directory is walked recursively."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="Files or directories to process (default: current directory).",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Do not print jpegoptim's own stdout/stderr; only summary lines.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run and validate, but do not modify any files.",
    )
    parser.add_argument(
        "-m",
        "--max",
        dest="max_quality",
        type=int,
        choices=QUALITY_RANGE,
        default=None,
        metavar="0-100",
        help=(
            "jpegoptim -m/--max value: maximum quality factor (0-100). "
            "When omitted, jpegoptim's default lossless-ish mode is used "
            "(existing quality is preserved)."
        ),
    )
    parser.add_argument(
        "--strip",
        action="store_true",
        help="Pass --strip-all to jpegoptim (remove all metadata markers).",
    )
    parser.add_argument(
        "--progressive",
        action="store_true",
        help="Pass --all-progressive to force progressive (interlaced) output.",
    )
    parser.add_argument(
        "--normal",
        action="store_true",
        help="Pass --all-normal to force baseline (non-progressive) output.",
    )
    parser.add_argument(
        "--jpegoptim",
        default="jpegoptim",
        metavar="PATH",
        help="Path to the jpegoptim executable (default: search PATH).",
    )
    parser.add_argument(
        "--jpegoptim-arg",
        action="append",
        default=[],
        metavar="ARG",
        help="Extra argument to pass to jpegoptim; may be repeated.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        metavar="SECONDS",
        help=f"Per-file jpegoptim timeout (default: {DEFAULT_TIMEOUT:g}s).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.progressive and args.normal:
        print(
            "error: --progressive and --normal are mutually exclusive",
            file=sys.stderr,
        )
        return 2
    roots = [Path(p) for p in args.paths] if args.paths else [Path()]
    worker = partial(
        process_file,
        jpegoptim=args.jpegoptim,
        max_quality=args.max_quality,
        strip=args.strip,
        progressive=args.progressive,
        normal=args.normal,
        extra_args=tuple(args.jpegoptim_arg),
        timeout=args.timeout,
        dry_run=args.dry_run,
    )
    counters: dict[str, int] = {
        "OK": 0,
        "DRY-RUN": 0,
        "NOCHG": 0,
        "SAME": 0,
        "SKIP": 0,
        "ERROR": 0,
    }
    total_before = 0
    total_after = 0
    files = iter_jpeg_files(roots)
    try:
        with Pool(processes=DEFAULT_WORKERS) as pool:
            for result in pool.imap_unordered(worker, files, chunksize=IMAP_CHUNKSIZE):
                if not args.quiet:
                    _emit_jpegoptim_output(result)
                tag = _classify(result, args.dry_run)
                counters[tag] += 1
                if tag in ("OK", "DRY-RUN"):
                    total_before += result.original_size
                    total_after += result.new_size
                _print_status(result, tag)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    _print_summary(counters, total_before, total_after)
    return 1 if counters["ERROR"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
