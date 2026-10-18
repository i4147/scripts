#!/data/data/com.termux/files/usr/bin/python
"""High-performance parallel directory archiver with flexible multiprocessing methods."""

from __future__ import annotations

import argparse
import bz2
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import gzip
import lzma
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import sys
import tarfile
from typing import IO, Any, Final, Literal, cast

from compression import zstd

Compressor = Literal["xz", "gz", "bz2", "zstd", "lz4"]

COMPRESSORS: Final[tuple[Compressor, ...]] = ("xz", "gz", "bz2", "zstd", "lz4")

EXTENSIONS: Final[dict[Compressor, str]] = {
    "xz": ".tar.xz",
    "gz": ".tar.gz",
    "bz2": ".tar.bz2",
    "zstd": ".tar.zst",
    "lz4": ".tar.lz4",
}


def _open_writer(path: Path, compressor: Compressor) -> IO[bytes]:
    if compressor == "xz":
        return lzma.open(path, "wb", preset=9 | lzma.PRESET_EXTREME)
    if compressor == "gz":
        return gzip.open(path, "wb", compresslevel=9)
    if compressor == "bz2":
        return bz2.open(path, "wb", compresslevel=9)
    if compressor == "zstd":
        return zstd.open(path, "wb", level=6)
    if compressor == "lz4":
        import lz4.frame

        return lz4.frame.open(
            path,
            "wb",
            compression_level=lz4.frame.COMPRESSIONLEVEL_MAX,
            block_size=lz4.frame.BLOCKSIZE_MAX4MB,
            block_linked=True,
            content_checksum=True,
        )
    raise ValueError(f"unsupported compressor: {compressor}")


def _open_reader(archive: Path) -> IO[bytes]:
    name = archive.name
    if name.endswith(".tar.xz"):
        return lzma.open(archive, "rb")
    if name.endswith(".tar.gz"):
        return gzip.open(archive, "rb")
    if name.endswith(".tar.bz2"):
        return bz2.open(archive, "rb")
    if name.endswith(".tar.zst"):
        return zstd.open(archive, "rb")
    if name.endswith(".tar.lz4"):
        import lz4.frame

        return lz4.frame.open(archive, "rb")
    raise ValueError(f"unsupported archive format: {archive}")


def _compress_one(args_tuple: tuple[Path, Compressor, bool, bool]) -> tuple[Path, bool, str | None]:
    directory, compressor, force, keep = args_tuple
    try:
        archive = directory.with_name(directory.name + EXTENSIONS[compressor])
        if archive.exists() and not force:
            return archive, False, "archive already exists (skipped)"

        with _open_writer(archive, compressor) as fh:
            with tarfile.open(fileobj=fh, mode="w", format=tarfile.PAX_FORMAT) as tar:
                tar.add(directory, arcname=directory.name, recursive=True)

        removed = False
        if not keep:
            shutil.rmtree(directory)
            removed = True
        return archive, removed, None
    except Exception as exc:
        return directory, False, str(exc)


def _decompress_one(args_tuple: tuple[Path, bool]) -> tuple[Path, bool, str | None]:
    archive, keep = args_tuple
    try:
        with _open_reader(archive) as fh:
            with tarfile.open(fileobj=fh, mode="r:") as tar:
                tar.extractall(path=archive.parent)

        removed = False
        if not keep:
            archive.unlink()
            removed = True
        return archive, removed, None
    except Exception as exc:
        return archive, False, str(exc)


def parallel_map(
    method: Literal["mp-map", "mp-imap", "process-pool", "thread-pool"],
    func: Any,
    items: list[Any],
    max_workers: int | None = None,
) -> list[Any]:
    if method == "thread-pool":
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            return list(executor.map(func, items))
    elif method == "process-pool":
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            return list(executor.map(func, items))
    elif method == "mp-map":
        with mp.Pool(processes=max_workers) as pool:
            return pool.map(func, items)
    elif method == "mp-imap":
        with mp.Pool(processes=max_workers) as pool:
            return list(pool.imap_unordered(func, items))
    else:
        raise ValueError(f"unknown multiprocessing method: {method}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tardirs", description="Compress or decompress top-level subdirectories in parallel."
    )
    parser.add_argument("-C", "--directory", type=Path, default=Path.cwd(), help="Target root directory")
    parser.add_argument(
        "-c",
        "--compressor",
        choices=COMPRESSORS,
        default="zstd",
        help="Compression algorithm to use",
    )
    parser.add_argument("-d", "--decompress", action="store_true", help="decompress archives in target directory")
    parser.add_argument("-j", "--jobs", type=int, default=4, help="Number of concurrent worker jobs")
    parser.add_argument("-f", "--force", action="store_true", help="Overwrite existing archives")
    parser.add_argument(
        "-k", "--keep", default=False, action="store_true", help="Keep source directories/archives after operation"
    )
    parser.add_argument(
        "--mp-method",
        type=str,
        default="process-pool",
        choices=["mp-map", "mp-imap", "process-pool", "thread-pool"],
        help="Parallel execution backend method",
    )
    ns = parser.parse_args()

    root: Path = ns.directory.resolve()
    compressor: Compressor = cast(Compressor, ns.compressor)
    decompress: bool = bool(ns.decompress)
    force: bool = bool(ns.force)
    keep: bool = bool(ns.keep)
    mp_method: Literal["mp-map", "mp-imap", "process-pool", "thread-pool"] = ns.mp_method

    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        raise SystemExit(2)

    cpu = os.cpu_count() or 4

    if decompress:
        subdirs = [p for p in root.iterdir() if p.is_dir()]
        if subdirs:
            print(f"error: subdirectories exist in {root}, refusing to decompress", file=sys.stderr)
            raise SystemExit(1)

        valid_suffixes = tuple(EXTENSIONS.values())
        targets: list[Path] = sorted(p for p in root.iterdir() if p.is_file() and p.name.endswith(valid_suffixes))
        if not targets:
            return

        max_workers: int = ns.jobs if isinstance(ns.jobs, int) and ns.jobs > 0 else min(len(targets), cpu)
        task_args = [(archive, keep) for archive in targets]

        print(f"Decompressing {len(targets)} archives using {mp_method} with {max_workers} worker(s)...")
        results = parallel_map(mp_method, _decompress_one, task_args, max_workers=max_workers)

        for res in results:
            archive, removed, err = res
            if err:
                print(f"error: {archive}: {err}", file=sys.stderr)
            else:
                suffix = " (removed archive)" if removed else ""
                print(f"{archive}{suffix}")
    else:
        # Only target top-level subdirectories inside root directory
        targets: list[Path] = sorted(p for p in root.iterdir() if p.is_dir())
        if not targets:
            print(f"No top-level subdirectories found in {root}.")
            return

        max_workers: int = ns.jobs if isinstance(ns.jobs, int) and ns.jobs > 0 else min(len(targets), cpu)
        task_args = [(d, compressor, force, keep) for d in targets]

        print(f"Compressing {len(targets)} top-level subdirectories using {mp_method} with {max_workers} worker(s)...")
        results = parallel_map(mp_method, _compress_one, task_args, max_workers=max_workers)

        for res in results:
            target_path, removed, err = res
            if err:
                print(f"error: {target_path}: {err}", file=sys.stderr)
            else:
                archive_name = (
                    target_path.with_name(target_path.name + EXTENSIONS[compressor])
                    if not target_path.name.endswith(tuple(EXTENSIONS.values()))
                    else target_path
                )
                suffix = " (removed source)" if removed else ""
                print(f"{archive_name}{suffix}")


if __name__ == "__main__":
    main()
