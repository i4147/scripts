#!/data/data/com.termux/files/usr/bin/python
import argparse
import bz2
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip
import lzma
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import sys
import tarfile
from typing import IO, Final, Literal, cast

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
        return zstd.open(path, "wb", level=19)
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


def _compress_one(directory: Path, compressor: Compressor, force: bool, keep: bool) -> tuple[Path, bool]:
    archive = directory.with_name(directory.name + EXTENSIONS[compressor])
    if archive.exists() and not force:
        return archive, False
    with _open_writer(archive, compressor) as fh:
        with tarfile.open(fileobj=fh, mode="w", format=tarfile.PAX_FORMAT) as tar:
            tar.add(directory, arcname=directory.name, recursive=True)
    removed = False
    if not keep:
        shutil.rmtree(directory)
        removed = True
    return archive, removed


def _decompress_one(archive: Path, keep: bool) -> tuple[Path, bool]:
    name = archive.name
    fh: IO[bytes]
    if name.endswith(".tar.xz"):
        fh = lzma.open(archive, "rb")
    elif name.endswith(".tar.gz"):
        fh = gzip.open(archive, "rb")
    elif name.endswith(".tar.bz2"):
        fh = bz2.open(archive, "rb")
    elif name.endswith(".tar.zst"):
        fh = zstd.open(archive, "rb")
    elif name.endswith(".tar.lz4"):
        import lz4.frame

        fh = lz4.frame.open(archive, "rb")
    else:
        raise ValueError(f"unsupported archive format: {archive}")

    with fh:
        with tarfile.open(fileobj=fh, mode="r:") as tar:
            tar.extractall(path=archive.parent)

    removed = False
    if not keep:
        archive.unlink()
        removed = True
    return archive, removed


def main() -> None:
    parser = argparse.ArgumentParser(prog="tardirs")
    parser.add_argument("-C", "--directory", type=Path, default=Path.cwd())
    parser.add_argument(
        "-c",
        "--compressor",
        choices=COMPRESSORS,
        default="lz4",
    )
    parser.add_argument("-d", "--decompress", action="store_true", help="decompress archives in target directory")
    parser.add_argument("-j", "--jobs", type=int, default=4)
    parser.add_argument("-f", "--force", action="store_true")
    parser.add_argument("-k", "--keep", default=False, action="store_true")
    ns = parser.parse_args()

    root: Path = ns.directory
    compressor: Compressor = cast(Compressor, ns.compressor)
    decompress: bool = bool(ns.decompress)
    force: bool = bool(ns.force)
    keep: bool = bool(ns.keep)

    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        raise SystemExit(2)

    if decompress:
        subdirs = [p for p in root.iterdir() if p.is_dir()]
        if subdirs:
            print(f"error: subdirectories exist in {root}, refusing to decompress", file=sys.stderr)
            raise SystemExit(1)

        valid_suffixes = tuple(EXTENSIONS.values())
        targets: list[Path] = sorted(p for p in root.iterdir() if p.is_file() and p.name.endswith(valid_suffixes))
        if not targets:
            return

        cpu = os.cpu_count() or 4
        max_workers: int = ns.jobs if isinstance(ns.jobs, int) and ns.jobs > 0 else min(len(targets), cpu)

        ctx = mp.get_context()
        with ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx) as pool:
            futures = {pool.submit(_decompress_one, d, keep): d for d in targets}
            for future in as_completed(futures):
                source = futures[future]
                try:
                    archive, removed = future.result()
                except Exception as exc:
                    print(f"error: {source}: {exc}", file=sys.stderr)
                else:
                    suffix = " (removed archive)" if removed else ""
                    print(f"{archive}{suffix}")
    else:
        targets: list[Path] = sorted(p for p in root.iterdir() if p.is_dir())
        if not targets:
            return

        cpu = os.process_cpu_count() or 1
        max_workers: int = ns.jobs if isinstance(ns.jobs, int) and ns.jobs > 0 else min(len(targets), cpu)

        ctx = mp.get_context()
        with ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx) as pool:
            futures = {pool.submit(_compress_one, d, compressor, force, keep): d for d in targets}
            for future in as_completed(futures):
                source = futures[future]
                try:
                    archive, removed = future.result()
                except Exception as exc:
                    print(f"error: {source}: {exc}", file=sys.stderr)
                else:
                    suffix = " (removed source)" if removed else ""
                    print(f"{archive}{suffix}")


if __name__ == "__main__":
    main()
