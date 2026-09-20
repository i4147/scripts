from __future__ import annotations

import argparse
import multiprocessing
import sys
import tarfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import brotli


LARGE_FILE_THRESHOLD = 5 * 1024 * 1024
LEVEL_DEFAULT = 11
LEVEL_LARGE = 3
BROTLI_EXT = ".br"
BROTLI_WINDOW_BITS = 24
BROTLI_BLOCK_BITS = 0
BROTLI_MODE = brotli.MODE_GENERIC
WORKERS = max(1, multiprocessing.cpu_count())
CHUMK_SIZE = 524288


def choose_level(path: Path) -> int:
    try:
        return LEVEL_LARGE if path.stat().st_size > LARGE_FILE_THRESHOLD else LEVEL_DEFAULT
    except OSError:
        return LEVEL_DEFAULT


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def compress_file(src: Path, dry_run: bool, verbose: bool, level: int | None = None) -> dict:
    result = {"src": src, "ok": False, "msg": ""}
    dst = src.with_suffix(src.suffix + BROTLI_EXT)
    if dst.exists():
        result["msg"] = f"skip — {dst.name} already exists"
        return result
    effective_level = level if level is not None else choose_level(src)
    if dry_run:
        result["ok"] = True
        result["msg"] = f"[dry-run] would compress {src} → {dst.name} (level {effective_level})"
        return result
    try:
        ctx = brotli.Compressor(
            quality=effective_level,
            lgwin=BROTLI_WINDOW_BITS,
            lgblock=BROTLI_BLOCK_BITS,
            mode=BROTLI_MODE,
        )
        with open(src, "rb") as f_in, open(dst, "wb") as f_out:
            while chunk := f_in.read(CHUNK_SIZE):
                f_out.write(ctx.compress(chunk))
            f_out.write(ctx.finish())
        orig_sz = src.stat().st_size
        comp_sz = dst.stat().st_size
        ratio = comp_sz / orig_sz * 100 if orig_sz else 0.0
        src.unlink()
        result["ok"] = True
        result["msg"] = (
            f"{src.name} → {dst.name} ({human(orig_sz)} → {human(comp_sz)}, {ratio:.1f}% saved, level {effective_level})"
        )
    except Exception as exc:
        result["msg"] = f"ERROR compressing {src}: {exc}"
    return result


def decompress_file(src: Path, dry_run: bool, verbose: bool) -> dict:
    result = {"src": src, "ok": False, "msg": ""}
    if src.suffix != BROTLI_EXT:
        result["msg"] = f"skip — not a .br file: {src.name}"
        return result
    dst = src.with_suffix("")
    if dst.exists():
        result["msg"] = f"skip — {dst.name} already exists"
        return result
    if dry_run:
        result["ok"] = True
        result["msg"] = f"[dry-run] would decompress {src} → {dst.name}"
        return result
    try:
        data = src.read_bytes()
        decompressed = brotli.decompress(data)
        dst.write_bytes(decompressed)
        src.unlink()
        result["ok"] = True
        result["msg"] = f"{src.name} → {dst.name} ({human(len(data))} → {human(len(decompressed))})"
    except Exception as exc:
        result["msg"] = f"ERROR decompressing {src}: {exc}"
    return result


def tar_subdir(subdir: Path, dry_run: bool, verbose: bool) -> Path | None:
    tar_path = subdir.parent / (subdir.name + ".tar")
    if dry_run:
        if verbose:
            print(f"  [dry-run] would tar {subdir}/ → {tar_path.name}")
        return tar_path
    try:
        with tarfile.open(tar_path, "w") as tf:
            tf.add(subdir, arcname=subdir.name)
        if verbose:
            print(f"  tarred {subdir.name}/ → {tar_path.name} ({human(tar_path.stat().st_size)})")
        return tar_path
    except Exception as exc:
        print(f"  ERROR tarring {subdir}: {exc}", file=sys.stderr)
        return None


def remove_subdir(subdir: Path, dry_run: bool, verbose: bool) -> None:
    if dry_run:
        if verbose:
            print(f"  [dry-run] would remove {subdir}/")
        return
    try:
        import shutil

        shutil.rmtree(subdir)
        if verbose:
            print(f"  removed original dir: {subdir.name}/")
    except Exception as exc:
        print(f"  WARNING — could not remove {subdir}: {exc}", file=sys.stderr)


def run_parallel(tasks: list, worker_fn, extra_kwargs: dict, verbose: bool) -> tuple[int, int]:
    ok = err = 0
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(worker_fn, path, **extra_kwargs): path for path in tasks}
        for fut in as_completed(futures):
            res = fut.result()
            if res["ok"]:
                ok += 1
                if verbose:
                    print(f"  ✓ {res['msg']}")
            else:
                err += 1
                print(f"  ✗ {res['msg']}", file=sys.stderr)
    return ok, err


def do_compress(root: Path, tar_subdirs: bool, dry_run: bool, verbose: bool) -> None:
    start = time.perf_counter()
    if tar_subdirs:
        subdirs = [p for p in root.iterdir() if p.is_dir()]
        if verbose:
            print(f"Taring {len(subdirs)} subdirectory/ies …")
        tar_paths = []
        for sd in subdirs:
            tp = tar_subdir(sd, dry_run, verbose)
            if tp:
                tar_paths.append((sd, tp))
        tar_files = [tp for _, tp in tar_paths]
        if tar_files:
            if verbose:
                print(f"Compressing {len(tar_files)} .tar archive(s) with level {LEVEL_LARGE} …")
            ok, err = run_parallel(
                tar_files,
                compress_file,
                {"dry_run": dry_run, "verbose": verbose, "level": LEVEL_LARGE},
                verbose,
            )
            compressed_tars = {tp for tp in tar_files if tp.with_suffix(tp.suffix + BROTLI_EXT).exists() or dry_run}
            for sd, tp in tar_paths:
                if tp in compressed_tars:
                    remove_subdir(sd, dry_run, verbose)
        loose = [p for p in root.iterdir() if p.is_file() and p.suffix != BROTLI_EXT]
        if loose:
            if verbose:
                print(f"Compressing {len(loose)} loose file(s) …")
            run_parallel(loose, compress_file, {"dry_run": dry_run, "verbose": verbose}, verbose)
    else:
        files = [p for p in root.rglob("*") if p.is_file() and p.suffix != BROTLI_EXT]
        if not files:
            print("No files to compress.")
            return
        if verbose:
            print(f"Compressing {len(files)} file(s) using {WORKERS} worker(s) …")
        ok, err = run_parallel(files, compress_file, {"dry_run": dry_run, "verbose": verbose}, verbose)
        elapsed = time.perf_counter() - start
        print(f"Done — {ok} compressed, {err} error(s) [{elapsed:.2f}s]")
        return
    elapsed = time.perf_counter() - start
    print(f"Done [{elapsed:.2f}s]")


def do_decompress(root: Path, dry_run: bool, verbose: bool) -> None:
    start = time.perf_counter()
    files = [p for p in root.rglob("*") if p.is_file() and p.suffix == BROTLI_EXT]
    if not files:
        print("No .br files found.")
        return
    if verbose:
        print(f"Decompressing {len(files)} file(s) using {WORKERS} worker(s) …")
    ok, err = run_parallel(files, decompress_file, {"dry_run": dry_run, "verbose": verbose}, verbose)
    elapsed = time.perf_counter() - start
    print(f"Done — {ok} decompressed, {err} error(s) [{elapsed:.2f}s]")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="brotli_compress",
        description="""Recursive brotli compression / decompression.
Default (no flags): compress files in CWD individually at level 11.""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "-c",
        "--compress",
        action="store_true",
        help="Compress files recursively (default when no mode flag given).",
    )
    mode.add_argument("-d", "--decompress", action="store_true", help="Decompress .br files recursively.")
    p.add_argument(
        "-t",
        "--tar-subdirs-first",
        action="store_true",
        help="Tar each immediate subdirectory before compressing. The .tar archive is then brotli-compressed and the original dir removed.",
    )
    p.add_argument("--verbose", action="store_true", help="Print per-file progress.")
    p.add_argument("--dry-run", action="store_true", help="Show what would happen without touching any files.")
    p.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Root directory to process (default: current directory).",
    )
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    root = Path(args.directory).resolve()
    if not root.is_dir():
        parser.error(f"Not a directory: {root}")
    compress = args.compress or not args.decompress
    if args.dry_run:
        print("[dry-run mode — no files will be modified]")
    if args.verbose or args.dry_run:
        print(f"Root : {root}")
        print(f"Mode : {'compress' if compress else 'decompress'}")
        if compress:
            print(f"Tar subdirs : {args.tar_subdirs_first}")
        print(f"Workers     : {WORKERS}")
        print()
    if compress:
        do_compress(root, args.tar_subdirs_first, args.dry_run, args.verbose)
    else:
        if args.tar_subdirs_first:
            print("Note: --tar-subdirs-first is ignored during decompression.", file=sys.stderr)
        do_decompress(root, args.dry_run, args.verbose)


if __name__ == "__main__":
    main()
