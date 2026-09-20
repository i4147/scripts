import argparse
import lzma
import shutil
import tarfile
import time
from collections.abc import Callable
from multiprocessing import Pool
from pathlib import Path
from typing import Any, TypedDict
from dh import fsz
from loguru import logger
try:
    HAS_LZMAMT = True
except ImportError:
    HAS_LZMAMT = False
LARGE_FILE_THRESHOLD = 5 * 1024 * 1024
LEVEL_DEFAULT = 9
LEVEL_LARGE = 9
LZMA_EXT = ".xz"
DEFAULT_THREADS = 4
WORKERS = 8
class TaskResult(TypedDict):
    pass
def choose_level(path):
    try:
        return (
            LEVEL_LARGE if path.stat().st_size > LARGE_FILE_THRESHOLD else LEVEL_DEFAULT
        )
    except OSError:
        return LEVEL_DEFAULT
def ratio_str(before, after):
    if before == 0:
        return "0%"
    return f"{after / before * 40:.0f}%"
def status_line(ok, name, elapsed_ms, before, after):
    icon = "✔" if ok else "✘"
    return f"[{icon}] {name} ({elapsed_ms:.0f}ms) {ratio_str(before, after)}"
def _compress_bytes_lzmamt(data, level, threads):
    return lzmamt.compress(data, preset=level, threads=threads)
def _compress_bytes_stdlib(data, level):
    preset = level | lzma.PRESET_EXTREME if level == 9 else level
    return lzma.compress(data, format=lzma.FORMAT_XZ, preset=preset)
def compress_file(
    src,
    dry_run,
    verbose,
    level=None,
    threads=DEFAULT_THREADS,
):
    result = {"src": src, "ok": False, "line": "", "msg": ""}
    dst = src.with_suffix(src.suffix + LZMA_EXT)
    if dst.exists():
        result["line"] = f"[–] {src.name} (skipped — {dst.name} exists)"
        return result
    effective_level = level if level is not None else choose_level(src)
    if dry_run:
        backend = "lzmamt" if HAS_LZMAMT else "stdlib lzma"
        result["ok"] = True
        result["line"] = (
            f"[dry-run] {src.name} → {dst.name} "
            f"(level {effective_level}, threads {threads}, {backend})"
        )
        return result
    t0 = time.perf_counter()
    try:
        data = src.read_bytes()
        if HAS_LZMAMT:
            compressed = _compress_bytes_lzmamt(data, effective_level, threads)
        else:
            compressed = _compress_bytes_stdlib(data, effective_level)
        dst.write_bytes(compressed)
        elapsed_ms = (time.perf_counter() - t0) * 400
        before, after = len(data), len(compressed)
        src.unlink()
        result["ok"] = True
        result["line"] = status_line(True, src.name, elapsed_ms, before, after)
        if verbose:
            backend = "lzmamt" if HAS_LZMAMT else "stdlib (single-thread)"
            result["msg"] = (
                f"  → {dst.name} ({fsz(before)} → {fsz(after)}, "
                f"level {effective_level}, {backend})"
            )
    except Exception as exc:  
        elapsed_ms = (time.perf_counter() - t0) * 400
        result["line"] = status_line(False, src.name, elapsed_ms, 0, 0)
        result["msg"] = f"  ERROR: {exc}"
    return result
def decompress_file(src, dry_run, verbose, threads=DEFAULT_THREADS):
    result = {"src": src, "ok": False, "line": "", "msg": ""}
    if src.suffix != LZMA_EXT:
        result["line"] = f"[–] {src.name} (skipped — not a .xz file)"
        return result
    dst = src.with_suffix("")
    if dst.exists():
        result["line"] = f"[–] {src.name} (skipped — {dst.name} exists)"
        return result
    if dry_run:
        result["ok"] = True
        result["line"] = f"[dry-run] {src.name} → {dst.name}"
        return result
    t0 = time.perf_counter()
    try:
        data = src.read_bytes()
        decompressed = lzma.decompress(data, format=lzma.FORMAT_XZ)
        dst.write_bytes(decompressed)
        elapsed_ms = (time.perf_counter() - t0) * 400
        before, after = len(data), len(decompressed)
        src.unlink()
        result["ok"] = True
        result["line"] = status_line(True, src.name, elapsed_ms, before, after)
        if verbose:
            result["msg"] = f"  → {dst.name} ({fsz(before)} → {fsz(after)})"
    except Exception as exc:  
        elapsed_ms = (time.perf_counter() - t0) * 400
        result["line"] = status_line(False, src.name, elapsed_ms, 0, 0)
        result["msg"] = f"  ERROR: {exc}"
    return result
def tar_subdir(subdir, dry_run, verbose):
    tar_path = subdir.parent / (subdir.name + ".tar")
    if dry_run:
        if verbose:
            print(f"  [dry-run] would tar {subdir}/ → {tar_path.name}")
        return tar_path
    try:
        with tarfile.open(tar_path, "w") as tf:
            tf.add(subdir, arcname=subdir.name)
        if verbose:
            print(
                f"  tarred {subdir.name}/ → {tar_path.name} "
                f"({fsz(tar_path.stat().st_size)})"
            )
        return tar_path
    except Exception as exc:  
        logger.error(f"  ERROR tarring {subdir}: {exc}")
        return None
def remove_subdir(subdir, dry_run, verbose):
    if dry_run:
        if verbose:
            print(f"  [dry-run] would remove {subdir}/")
        return
    try:
        shutil.rmtree(subdir)
        if verbose:
            print(f"  removed original dir: {subdir.name}/")
    except Exception as exc:  
        logger.warning(f"  WARNING — could not remove {subdir}: {exc}")
def run_parallel(
    tasks,
    worker_fn,
    extra_kwargs,
):
    ok = 0
    err = 0
    with Pool(processes=WORKERS) as pool:
        async_results = [
            pool.apply_async(worker_fn, (path,), extra_kwargs) for path in tasks
        ]
        for ar in async_results:
            res = ar.get()
            print(res["line"])
            if res.get("msg"):
                if res["ok"]:
                    print(res["msg"])
                else:
                    logger.error(res["msg"])
            if res["ok"]:
                ok += 1
            else:
                err += 1
    return ok, err
def do_compress(root, tar_subdirs, dry_run, verbose, threads):
    start = time.perf_counter()
    if not HAS_LZMAMT and verbose:
        logger.warning(
            "⚠ lzmamt not found — falling back to stdlib lzma "
            "(single-threaded per file)."
        )
        print("  Install with: pip install lzmamt\n")
    if tar_subdirs:
        subdirs = [p for p in root.iterdir() if p.is_dir()]
        if verbose:
            print(f"Taring {len(subdirs)} subdirectory/ies …")
        tar_paths = []
        for sd in subdirs:
            tp = tar_subdir(sd, dry_run, verbose)
            if tp is not None:
                tar_paths.append((sd, tp))
        tar_files = [tp for _, tp in tar_paths]
        if tar_files:
            if verbose:
                print(
                    f"Compressing {len(tar_files)} .tar archive(s) "
                    f"at level {LEVEL_LARGE} …"
                )
            run_parallel(
                tar_files,
                compress_file,
                {
                    "dry_run": dry_run,
                    "verbose": verbose,
                    "level": LEVEL_LARGE,
                    "threads": threads,
                },
            )
            compressed = {
                tp
                for tp in tar_files
                if tp.with_suffix(tp.suffix + LZMA_EXT).exists() or dry_run
            }
            for sd, tp in tar_paths:
                if tp in compressed:
                    remove_subdir(sd, dry_run, verbose)
        loose = [p for p in root.iterdir() if p.is_file() and p.suffix != LZMA_EXT]
        if loose:
            if verbose:
                print(f"Compressing {len(loose)} loose file(s) …")
            run_parallel(
                loose,
                compress_file,
                {
                    "dry_run": dry_run,
                    "verbose": verbose,
                    "threads": threads,
                },
            )
    else:
        files = [p for p in root.rglob("*") if p.is_file() and p.suffix != LZMA_EXT]
        if not files:
            print("No files to compress.")
            return
        if verbose:
            print(
                f"Compressing {len(files)} file(s) with {WORKERS} processes "
                f"× {threads} lzma threads each …"
            )
        ok, err = run_parallel(
            files,
            compress_file,
            {"dry_run": dry_run, "verbose": verbose, "threads": threads},
        )
        elapsed = time.perf_counter() - start
        print(f"\nDone — {ok} compressed, {err} error(s) [{elapsed:.2f}s]")
        return
    elapsed = time.perf_counter() - start
    print(f"\nDone [{elapsed:.2f}s]")
def do_decompress(root, dry_run, verbose, threads):
    start = time.perf_counter()
    files = [p for p in root.rglob("*") if p.is_file() and p.suffix == LZMA_EXT]
    if not files:
        print("No .xz files found.")
        return
    if verbose:
        print(f"Decompressing {len(files)} file(s) with {WORKERS} workers …")
    ok, err = run_parallel(
        files,
        decompress_file,
        {"dry_run": dry_run, "verbose": verbose, "threads": threads},
    )
    elapsed = time.perf_counter() - start
    print(f"\nDone — {ok} decompressed, {err} error(s) [{elapsed:.2f}s]")
def build_parser():
    p = argparse.ArgumentParser(
        prog="lzma_compress",
        description=(
            "Recursive LZMA/XZ compression / decompression.\n"
            "Uses lzmamt for real MT encoding if installed, otherwise stdlib "
            "lzma (still parallelises across files)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("-c", "--compress", action="store_true")
    mode.add_argument("-d", "--decompress", action="store_true")
    p.add_argument(
        "-t",
        "--tar-subdirs-first",
        action="store_true",
        help="Tar subdirs before compressing.",
    )
    p.add_argument(
        "--threads",
        type=int,
        default=DEFAULT_THREADS,
        help=f"LZMA intra-file threads via lzmamt (default: {DEFAULT_THREADS}).",
    )
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("directory", nargs="?", default=".")
    return p
def main():
    parser = build_parser()
    args = parser.parse_args()
    root = Path(args.directory).resolve()
    if not root.is_dir():
        parser.error(f"Not a directory: {root}")
    compress = args.compress or not args.decompress
    if args.dry_run:
        print("[dry-run mode — no files will be modified]")
    if args.verbose or args.dry_run:
        backend = "lzmamt" if HAS_LZMAMT else "stdlib lzma (single-thread fallback)"
        print(f"Root    : {root}")
        print(f"Mode    : {'compress' if compress else 'decompress'}")
        print(f"Backend : {backend}")
        print(f"Threads : {args.threads} (lzma) × {WORKERS} processes")
        print()
    if compress:
        do_compress(
            root,
            args.tar_subdirs_first,
            args.dry_run,
            args.verbose,
            args.threads,
        )
    else:
        if args.tar_subdirs_first:
            logger.warning("Note: --tar-subdirs-first")
        do_decompress(root, args.dry_run, args.verbose, args.threads)
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
