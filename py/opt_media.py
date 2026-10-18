from __future__ import annotations

import argparse
import contextlib
from functools import partial
from multiprocessing import Pool
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import TYPE_CHECKING, Final, NamedTuple
import xml.etree.ElementTree as ET

from dh import fsz, walker

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

cwd: Final[Path] = Path.cwd().resolve()

JPEG_MAGIC: Final[bytes] = b"\xff\xd8\xff"
PNG_MAGIC: Final[bytes] = b"\x89PNG\r\n\x1a\n"

JPEG_SUFFIXES: Final[frozenset[str]] = frozenset({".jpg", ".jpeg"})
PNG_SUFFIXES: Final[frozenset[str]] = frozenset({".png"})
SVG_SUFFIXES: Final[frozenset[str]] = frozenset({".svg"})
ALL_SUFFIXES: Final[list[str]] = [".jpg", ".jpeg", ".png", ".svg"]

KIND_SUFFIXES: Final[dict[str, tuple[str, ...]]] = {
    "jpg": (".jpg", ".jpeg"),
    "png": (".png",),
    "svg": (".svg",),
}

DEFAULT_WORKERS: Final[int] = 8
IMAP_CHUNKSIZE: Final[int] = 4
DEFAULT_TIMEOUT: Final[float] = 300.0
COMPARE_CHUNK: Final[int] = 1 << 16
JPEGOPTIM_SUCCESS: Final[int] = 0
PNGQUANT_SUCCESS: Final[int] = 0
PNGQUANT_ALREADY_OPTIMAL: Final[int] = 25
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


class Config(NamedTuple):
    jpegoptim: str
    max_quality: int | None
    strip: bool
    progressive: bool
    normal: bool
    jpegoptim_extra: tuple[str, ...]
    pngquant: str
    png_quality: str | None
    png_speed: int | None
    png_posterize: int | None
    pngquant_extra: tuple[str, ...]
    svgo: str
    svg_multipass: bool
    svg_pretty: bool
    svgo_extra: tuple[str, ...]
    timeout: float
    dry_run: bool


def _kind_of(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in JPEG_SUFFIXES:
        return "jpg"
    if suffix in PNG_SUFFIXES:
        return "png"
    if suffix in SVG_SUFFIXES:
        return "svg"
    return None


def _display(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(cwd))
    except (ValueError, OSError):
        return str(p)


def _stage_temp(target: Path) -> Path | None:
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=target.stem + ".",
            suffix=target.suffix + ".tmp",
            dir=os.environ.get("TMPDIR") or None,
        )
        with contextlib.suppress(OSError):
            os.close(fd)
        return Path(tmp_name)
    except OSError:
        return None


def _files_identical(a: Path, b: Path, a_size: int, b_size: int) -> bool:
    if a_size != b_size:
        return False
    with a.open("rb") as fa, b.open("rb") as fb:
        while True:
            ca = fa.read(COMPARE_CHUNK)
            cb = fb.read(COMPARE_CHUNK)
            if ca != cb:
                return False
            if not ca:
                return True


def _validate_jpeg(path: Path) -> str | None:
    try:
        with path.open("rb") as f:
            header = f.read(len(JPEG_MAGIC))
    except OSError as exc:
        return f"cannot read output: {exc}"
    return None if header == JPEG_MAGIC else "output is not a JPEG (bad signature)"


def _validate_png(path: Path) -> str | None:
    try:
        with path.open("rb") as f:
            header = f.read(len(PNG_MAGIC))
    except OSError as exc:
        return f"cannot read output: {exc}"
    return None if header == PNG_MAGIC else "output is not a PNG (bad signature)"


def _validate_svg(path: Path) -> str | None:
    try:
        ET.parse(path)
    except ET.ParseError as exc:
        return f"output is not well-formed XML: {exc}"
    except OSError as exc:
        return f"cannot read output: {exc}"
    return None


def _run_tool(
    cmd: Sequence[str], timeout: float, label: str
) -> tuple[subprocess.CompletedProcess[bytes] | None, str, str, str | None]:
    try:
        completed = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return None, "", "", f"{label} timed out after {timeout:g}s"
    except FileNotFoundError:
        return None, "", "", f"{label} executable not found: {cmd[0]!r}"
    except OSError as exc:
        return None, "", "", f"failed to run {label}: {exc}"
    return (
        completed,
        completed.stdout.decode("utf-8", errors="replace"),
        completed.stderr.decode("utf-8", errors="replace"),
        None,
    )


def _finalize(
    path: Path,
    target: Path,
    tmp_path: Path,
    original_size: int,
    original_mode: int,
    stdout: str,
    stderr: str,
    validator: Callable[[Path], str | None],
    dry_run: bool,
) -> ProcessResult:
    committed = False
    try:
        try:
            new_size = tmp_path.stat().st_size
        except OSError as exc:
            return ProcessResult(
                path, original_size, 0, stdout, stderr, False, False, f"tool produced no output: {exc}"
            )
        if new_size == 0:
            return ProcessResult(path, original_size, 0, stdout, stderr, False, False, "tool produced an empty file")
        sig_err = validator(tmp_path)
        if sig_err is not None:
            return ProcessResult(path, original_size, new_size, stdout, stderr, False, False, sig_err)
        try:
            identical = _files_identical(target, tmp_path, original_size, new_size)
        except OSError as exc:
            return ProcessResult(
                path, original_size, new_size, stdout, stderr, False, False, f"cannot compare files: {exc}"
            )
        if identical:
            return ProcessResult(path, original_size, original_size, stdout, stderr, False, True, None)
        if new_size > original_size:
            return ProcessResult(path, original_size, new_size, stdout, stderr, True, False, None)
        if new_size == original_size:
            return ProcessResult(path, original_size, new_size, stdout, stderr, True, False, None)
        if dry_run:
            return ProcessResult(path, original_size, new_size, stdout, stderr, False, False, None)
        try:
            os.chmod(tmp_path, original_mode)
            shutil.copy2(tmp_path, target)
            os.remove(tmp_path)
        except OSError as exc:
            return ProcessResult(
                path, original_size, new_size, stdout, stderr, False, False, f"failed to replace original: {exc}"
            )
        committed = True
        return ProcessResult(path, original_size, new_size, stdout, stderr, False, False, None)
    finally:
        if not committed:
            with contextlib.suppress(OSError):
                tmp_path.unlink()


def _resolve_target(path: Path) -> tuple[Path | None, os.stat_result | None, str | None]:
    try:
        target = path.resolve(strict=True)
    except OSError as exc:
        return None, None, f"cannot resolve: {exc}"
    try:
        st = target.stat()
    except OSError as exc:
        return None, None, f"cannot stat: {exc}"
    return target, st, None


def _process_jpg(path: Path, cfg: Config) -> ProcessResult:
    target, st, err = _resolve_target(path)
    if err is not None:
        return ProcessResult(path, 0, 0, "", "", False, False, err)
    assert target is not None and st is not None
    original_size = st.st_size
    original_mode = stat.S_IMODE(st.st_mode)
    tmp_path = _stage_temp(target)
    if tmp_path is None:
        return ProcessResult(path, original_size, 0, "", "", False, False, "cannot create temp file")
    try:
        try:
            shutil.copy2(target, tmp_path)
        except OSError as exc:
            return ProcessResult(path, original_size, 0, "", "", False, False, f"cannot stage temp copy: {exc}")
        cmd: list[str] = [cfg.jpegoptim]
        if cfg.max_quality is not None:
            cmd += ["-m", str(cfg.max_quality)]
        if cfg.strip:
            cmd.append("--strip-all")
        if cfg.progressive and not cfg.normal:
            cmd.append("--all-progressive")
        if cfg.normal and not cfg.progressive:
            cmd.append("--all-normal")
        cmd.extend(cfg.jpegoptim_extra)
        cmd.extend(["--", str(tmp_path)])
        completed, stdout, stderr, err = _run_tool(cmd, cfg.timeout, "jpegoptim")
        if err is not None:
            return ProcessResult(path, original_size, 0, stdout, stderr, False, False, err)
        assert completed is not None
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
        return _finalize(
            path, target, tmp_path, original_size, original_mode, stdout, stderr, _validate_jpeg, cfg.dry_run
        )
    finally:
        with contextlib.suppress(OSError):
            tmp_path.unlink()


def _process_png(path: Path, cfg: Config) -> ProcessResult:
    target, st, err = _resolve_target(path)
    if err is not None:
        return ProcessResult(path, 0, 0, "", "", False, False, err)
    assert target is not None and st is not None
    original_size = st.st_size
    original_mode = stat.S_IMODE(st.st_mode)
    tmp_path = _stage_temp(target)
    if tmp_path is None:
        return ProcessResult(path, original_size, 0, "", "", False, False, "cannot create temp file")
    try:
        cmd: list[str] = [cfg.pngquant]
        if cfg.png_quality is not None:
            cmd += ["--quality", cfg.png_quality]
        if cfg.png_speed is not None:
            cmd += ["--speed", str(cfg.png_speed)]
        if cfg.strip:
            cmd.append("--strip")
        if cfg.png_posterize is not None:
            cmd += ["--posterize", str(cfg.png_posterize)]
        cmd.extend(cfg.pngquant_extra)
        cmd += ["--force", "--output", str(tmp_path), "--", str(target)]
        completed, stdout, stderr, err = _run_tool(cmd, cfg.timeout, "pngquant")
        if err is not None:
            return ProcessResult(path, original_size, 0, stdout, stderr, False, False, err)
        assert completed is not None
        if completed.returncode == PNGQUANT_ALREADY_OPTIMAL:
            return ProcessResult(path, original_size, original_size, stdout, stderr, False, True, None)
        if completed.returncode != PNGQUANT_SUCCESS:
            return ProcessResult(
                path,
                original_size,
                0,
                stdout,
                stderr,
                False,
                False,
                f"pngquant exited with status {completed.returncode}",
            )
        return _finalize(
            path, target, tmp_path, original_size, original_mode, stdout, stderr, _validate_png, cfg.dry_run
        )
    finally:
        with contextlib.suppress(OSError):
            tmp_path.unlink()


def _process_svg(path: Path, cfg: Config) -> ProcessResult:
    target, st, err = _resolve_target(path)
    if err is not None:
        return ProcessResult(path, 0, 0, "", "", False, False, err)
    assert target is not None and st is not None
    original_size = st.st_size
    original_mode = stat.S_IMODE(st.st_mode)
    tmp_path = _stage_temp(target)
    if tmp_path is None:
        return ProcessResult(path, original_size, 0, "", "", False, False, "cannot create temp file")
    try:
        cmd: list[str] = [cfg.svgo]
        if cfg.svg_multipass:
            cmd.append("--multipass")
        if cfg.svg_pretty:
            cmd.append("--pretty")
        cmd.extend(cfg.svgo_extra)
        cmd.extend(["-i", str(target), "-o", str(tmp_path)])
        completed, stdout, stderr, err = _run_tool(cmd, cfg.timeout, "svgo")
        if err is not None:
            return ProcessResult(path, original_size, 0, stdout, stderr, False, False, err)
        assert completed is not None
        if completed.returncode != 0:
            return ProcessResult(
                path, original_size, 0, stdout, stderr, False, False, f"svgo exited with status {completed.returncode}"
            )
        return _finalize(
            path, target, tmp_path, original_size, original_mode, stdout, stderr, _validate_svg, cfg.dry_run
        )
    finally:
        with contextlib.suppress(OSError):
            tmp_path.unlink()


def _process_file(path: Path, config: Config) -> ProcessResult:
    kind = _kind_of(path)
    if kind == "jpg":
        return _process_jpg(path, config)
    if kind == "png":
        return _process_png(path, config)
    if kind == "svg":
        return _process_svg(path, config)
    return ProcessResult(path, 0, 0, "", "", False, False, f"unsupported file: {path.suffix}")


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


def _emit_tool_output(result: ProcessResult) -> None:
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
    rel = _display(result.path)
    orig = result.original_size
    new = result.new_size
    if tag == "OK":
        saved = orig - new
        pct = (saved / orig * 100.0) if orig else 0.0
        print(f"[OK]      {rel}  {fsz(orig)} -> {fsz(new)}  (-{fsz(saved)}, -{pct:.1f}%)")
    elif tag == "DRY-RUN":
        saved = orig - new
        pct = (saved / orig * 100.0) if orig else 0.0
        print(f"[DRY-RUN] {rel}  {fsz(orig)} -> {fsz(new)}  (would save {fsz(saved)}, {pct:.1f}%)")
    elif tag == "NOCHG":
        print(f"[NOCHG]   {rel}  {fsz(orig)}  (byte-identical)")
    elif tag == "SAME":
        print(f"[SAME]    {rel}  {fsz(orig)}  (same size, different bytes)")
    elif tag == "SKIP":
        growth = new - orig
        print(f"[SKIP]    {rel}  {fsz(orig)} -> {fsz(new)}  (larger by {fsz(growth)})")
    else:
        print(f"[ERROR]   {rel}  {result.error}", file=sys.stderr)


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
        print(f"  Bytes     : {fsz(total_before)} -> {fsz(total_after)}  (saved {fsz(saved)}, {pct:.1f}%)")
    else:
        print()
        print("  Bytes     : no size changes")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opt-media",
        description=(
            "Optimize JPG/JPEG (jpegoptim), PNG (pngquant), and SVG (svgo) files "
            "in place. With no paths, the current directory is walked recursively."
        ),
    )
    parser.add_argument("paths", nargs="*", metavar="PATH", help="Files or directories (default: current directory).")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress tool stdout/stderr; only status lines.")
    parser.add_argument("--dry-run", action="store_true", help="Run and validate, but do not modify any files.")
    parser.add_argument(
        "--only",
        action="append",
        choices=["jpg", "png", "svg"],
        default=None,
        help="Restrict to these kinds (repeatable). Default: all.",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=DEFAULT_WORKERS,
        metavar="N",
        help=f"Worker count (default: {DEFAULT_WORKERS}).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        metavar="SECONDS",
        help=f"Per-file tool timeout (default: {DEFAULT_TIMEOUT:g}s).",
    )

    jpg = parser.add_argument_group("jpegoptim")
    jpg.add_argument(
        "--max",
        dest="max_quality",
        type=int,
        choices=QUALITY_RANGE,
        default=None,
        metavar="0-100",
        help="jpegoptim -m (max quality).",
    )
    jpg.add_argument("--strip", action="store_true", help="Strip metadata (jpegoptim --strip-all, pngquant --strip).")
    jpg.add_argument("--progressive", action="store_true", help="jpegoptim --all-progressive.")
    jpg.add_argument("--normal", action="store_true", help="jpegoptim --all-normal.")
    jpg.add_argument(
        "--jpegoptim", default="jpegoptim", metavar="PATH", help="Path to jpegoptim (default: search PATH)."
    )
    jpg.add_argument(
        "--jpegoptim-arg", action="append", default=[], metavar="ARG", help="Extra arg to jpegoptim (repeatable)."
    )

    png = parser.add_argument_group("pngquant")
    png.add_argument(
        "--quality", dest="png_quality", default=None, metavar="MIN-MAX", help="pngquant --quality (e.g. '65-80')."
    )
    png.add_argument(
        "--speed",
        dest="png_speed",
        type=int,
        choices=range(1, 12),
        default=None,
        metavar="1-11",
        help="pngquant --speed (1 slowest, 11 fastest).",
    )
    png.add_argument(
        "--posterize",
        dest="png_posterize",
        type=int,
        choices=range(5),
        default=None,
        metavar="0-4",
        help="pngquant --posterize.",
    )
    png.add_argument("--pngquant", default="pngquant", metavar="PATH", help="Path to pngquant (default: search PATH).")
    png.add_argument(
        "--pngquant-arg", action="append", default=[], metavar="ARG", help="Extra arg to pngquant (repeatable)."
    )

    svg = parser.add_argument_group("svgo")
    svg.add_argument("--multipass", action="store_true", help="svgo --multipass.")
    svg.add_argument("--pretty", action="store_true", help="svgo --pretty.")
    svg.add_argument("--svgo", default="svgo", metavar="PATH", help="Path to svgo (default: search PATH).")
    svg.add_argument("--svgo-arg", action="append", default=[], metavar="ARG", help="Extra arg to svgo (repeatable).")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.progressive and args.normal:
        print("error: --progressive and --normal are mutually exclusive", file=sys.stderr)
        return 2

    only = args.only or ["jpg", "png", "svg"]
    only_set = set(only)
    exts: list[str] = []
    for k in only:
        exts.extend(KIND_SUFFIXES[k])

    available: set[str] = set()
    for kind, tool in (("jpg", args.jpegoptim), ("png", args.pngquant), ("svg", args.svgo)):
        if kind not in only_set:
            continue
        if shutil.which(tool):
            available.add(kind)
        else:
            print(f"warning: {tool!r} not found (skipping {kind} files)", file=sys.stderr)
    if not available:
        print("error: no usable tools available", file=sys.stderr)
        return 1

    cfg = Config(
        jpegoptim=args.jpegoptim,
        max_quality=args.max_quality,
        strip=args.strip,
        progressive=args.progressive,
        normal=args.normal,
        jpegoptim_extra=tuple(args.jpegoptim_arg),
        pngquant=args.pngquant,
        png_quality=args.png_quality,
        png_speed=args.png_speed,
        png_posterize=args.png_posterize,
        pngquant_extra=tuple(args.pngquant_arg),
        svgo=args.svgo,
        svg_multipass=args.multipass,
        svg_pretty=args.pretty,
        svgo_extra=tuple(args.svgo_arg),
        timeout=args.timeout,
        dry_run=args.dry_run,
    )

    roots = [Path(p) for p in args.paths] if args.paths else [Path()]
    available_snapshot = frozenset(available)

    def _iter_files() -> Iterator[Path]:
        for root in roots:
            for p in walker(root, exts=exts):
                if _kind_of(p) in available_snapshot:
                    yield p

    worker = partial(_process_file, config=cfg)
    counters: dict[str, int] = {"OK": 0, "DRY-RUN": 0, "NOCHG": 0, "SAME": 0, "SKIP": 0, "ERROR": 0}
    total_before = 0
    total_after = 0

    try:
        with Pool(processes=args.jobs) as pool:
            for result in pool.imap_unordered(worker, _iter_files(), chunksize=IMAP_CHUNKSIZE):
                if not args.quiet:
                    _emit_tool_output(result)
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
