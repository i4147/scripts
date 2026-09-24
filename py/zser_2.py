from __future__ import annotations

from argparse import Namespace
import gc
import os
import sys
import shutil
from pathlib import Path
import tarfile
import argparse
import concurrent.futures

from dh import MAX_WORKERS
from dh import fsz
from dh import gsz
from dh import cprint
import zstandard as zstd


COMPRESSED_EXTS = frozenset({".xz", ".br", ".7z", ".zip", ".gz", ".bz2", ".zst", ".whl"})
ZST_EXT = ".zst"


def should_compress(path: Path) -> bool:
    try:
        if not path.is_file():
            return False
        if path.suffix in COMPRESSED_EXTS:
            return False
        if path.suffix == ZST_EXT:
            return False
        return path.stat().st_size > 0
    except (OSError, PermissionError):
        return False


def should_decompress(path: Path) -> bool:
    try:
        if not path.is_file():
            return False
        if path.suffix != ZST_EXT:
            return False
        return path.stat().st_size > 0
    except (OSError, PermissionError):
        return False


def list_items_compress(target: Path) -> tuple[list[Path], list[Path]]:
    dirs = []
    files = []
    try:
        with os.scandir(target) as it:
            for entry in it:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        dirs.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False) and should_compress(Path(entry.path)):
                        files.append(Path(entry.path))
                except (OSError, PermissionError):
                    continue
    except (OSError, PermissionError):
        pass
    return sorted(dirs), sorted(files)


def list_files_decompress(target: Path) -> list[Path]:
    files = []
    try:
        with os.scandir(target) as it:
            for entry in it:
                try:
                    if entry.is_file(follow_symlinks=False) and should_decompress(Path(entry.path)):
                        files.append(Path(entry.path))
                except (OSError, PermissionError):
                    continue
    except (OSError, PermissionError):
        pass
    return sorted(files)


def compress_folder_sync(
    folder_path: Path,
    output_base_name: str,
    fmt: str = "tar",
    level: int = 3,
    zstd_threads: int = 1,
    chunk_size: int = 65536,
) -> tuple[bool, str | None]:
    tar_path = None
    zst_path = None
    try:
        if fmt == "tar":
            tar_path = f"{output_base_name}.tar"
            with tarfile.open(tar_path, "w") as tar:
                tar.add(str(folder_path), arcname=folder_path.name)

            zst_path = tar_path + ZST_EXT

            cctx = zstd.ZstdCompressor(level=level, threads=zstd_threads)
            with open(tar_path, "rb", buffering=chunk_size) as fin:
                with open(zst_path, "wb", buffering=chunk_size) as fout:
                    compressor = cctx.stream_reader(fin, read_size=chunk_size)
                    while True:
                        chunk = compressor.read(chunk_size)
                        if not chunk:
                            break
                        fout.write(chunk)
                    compressor.close()

            os.unlink(tar_path)
            return True, zst_path
        return False, f"Unsupported format: {fmt}"
    except Exception as e:
        if tar_path and os.path.exists(tar_path):
            os.unlink(tar_path)
        if zst_path and os.path.exists(zst_path):
            os.unlink(zst_path)
        return False, str(e)
    finally:
        gc.collect()


def compress_file_streaming(path: Path, level: int, zstd_threads: int, chunk_size: int) -> dict:
    dst = path.with_suffix(path.suffix + ZST_EXT)

    if dst.exists():
        return {"skipped": True, "path": path, "action": "compress"}

    try:
        file_size = path.stat().st_size
        if file_size == 0:
            return {"skipped": True, "path": path, "action": "compress"}

        cctx = zstd.ZstdCompressor(level=level, threads=zstd_threads)

        with open(path, "rb", buffering=chunk_size) as fin, open(dst, "wb", buffering=chunk_size) as fout:
            reader = cctx.stream_reader(fin, read_size=chunk_size)
            while True:
                chunk = reader.read(chunk_size)
                if not chunk:
                    break
                fout.write(chunk)
            reader.close()

        compressed_size = dst.stat().st_size
        if compressed_size == 0:
            dst.unlink(missing_ok=True)
            return {"error": "empty output", "path": path, "action": "compress"}

        path.unlink()

        return {
            "success": True,
            "path": path,
            "original_size": file_size,
            "compressed_size": compressed_size,
            "skipped": False,
            "action": "compress",
        }

    except Exception as e:
        if dst.exists():
            try:
                if dst.stat().st_size == 0:
                    dst.unlink(missing_ok=True)
            except Exception:
                pass
        return {"error": str(e), "path": path, "skipped": False, "action": "compress"}


def decompress_file_streaming(path: Path, chunk_size: int) -> dict:

    dst = path.with_suffix("")

    if path.suffixes and len(path.suffixes) > 1:
        dst = path.with_suffix("").with_suffix(path.suffixes[-2])

    if dst.exists():
        return {"skipped": True, "path": path, "dst": dst, "action": "decompress"}

    try:
        file_size = path.stat().st_size
        if file_size == 0:
            return {"skipped": True, "path": path, "dst": dst, "action": "decompress"}

        dctx = zstd.ZstdDecompressor()

        with open(path, "rb", buffering=chunk_size) as fin, open(dst, "wb", buffering=chunk_size) as fout:
            reader = dctx.stream_reader(fin, read_size=chunk_size)
            while True:
                chunk = reader.read(chunk_size)
                if not chunk:
                    break
                fout.write(chunk)
            reader.close()

        decompressed_size = dst.stat().st_size
        if decompressed_size == 0:
            dst.unlink(missing_ok=True)
            return {"error": "empty output", "path": path, "dst": dst, "action": "decompress"}

        path.unlink()

        return {
            "success": True,
            "path": path,
            "dst": dst,
            "original_size": file_size,
            "decompressed_size": decompressed_size,
            "skipped": False,
            "action": "decompress",
        }

    except Exception as e:
        if dst.exists():
            try:
                if dst.stat().st_size == 0:
                    dst.unlink(missing_ok=True)
            except Exception:
                pass
        return {"error": str(e), "path": path, "dst": dst, "skipped": False, "action": "decompress"}


def process_compress_batch(files_batch: list[Path], level: int, zstd_threads: int, chunk_size: int) -> list[dict]:
    results = []
    for file_path in files_batch:
        result = compress_file_streaming(file_path, level, zstd_threads, chunk_size)
        results.append(result)
    return results


def process_decompress_batch(files_batch: list[Path], chunk_size: int) -> list[dict]:
    results = []
    for file_path in files_batch:
        result = decompress_file_streaming(file_path, chunk_size)
        results.append(result)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Memory-optimized parallel zstd compressor/decompressor for a directory."
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "-c", "--compress", default=True, action="store_true", help="Compress files in the target directory"
    )
    mode_group.add_argument(
        "-d", "--decompress", action="store_true", help="Decompress .zst files in the target directory"
    )

    parser.add_argument("--workers", type=int, default=0, help="Number of parallel workers ")
    parser.add_argument("--chunk-size", type=int, default=65536, help="Read/write buffer size in bytes (default 65536)")
    parser.add_argument("path", nargs="?", default=".", help="Target directory (default: current)")

    parser.add_argument(
        "--level", type=int, default=3, help="Compression level for zstd (1-22, default 3, lower = faster)"
    )
    parser.add_argument(
        "--format",
        type=str,
        default="tar",
        choices=("tar", "zip"),
        help="Archive format for directories in compress mode (default: tar)",
    )

    args = parser.parse_args()

    target = Path(args.path).resolve()
    if not target.is_dir():
        print("Target must be a directory", file=sys.stderr)
        return 2

    workers = MAX_WORKERS
    zstd_threads = MAX_WORKERS
    chunk_size = 1_048_576

    before_total = gsz(target)

    if args.compress:
        return handle_compress(target, args, workers, zstd_threads, chunk_size, before_total)

    return handle_decompress(target, args, workers, chunk_size, before_total)


def handle_compress(
    target: Path, args: Namespace, workers: int, zstd_threads: int, chunk_size: int, before_total: int
) -> int:
    dirs, files = list_items_compress(target)
    ok: bool = False
    for d in dirs:
        base = str(d.parent / d.name)
        ok, info = compress_folder_sync(
            d, base, fmt=args.format, level=args.level, zstd_threads=zstd_threads, chunk_size=chunk_size
        )

    if ok:
        print(f"compressed {d.relative_to(target)} -> {Path(info).name}")
        try:
            shutil.rmtree(d)
            gc.collect()
        except Exception as e:
            print(f"warning: failed to remove {d}: {e}")
    else:
        print(f"failed to compress directory {d}: {info}")
    if not files:
        print("No files to compress")
        return 0

    batch_size = max(1, min(10, len(files) // max(1, workers)))
    batches = [files[i : i + batch_size] for i in range(0, len(files), batch_size)]

    total_original = 0
    total_compressed = 0
    successful = 0
    total_files = len(files)
    processed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        future_to_batch = {
            ex.submit(process_compress_batch, batch, args.level, zstd_threads, chunk_size): batch for batch in batches
        }

        for future in concurrent.futures.as_completed(future_to_batch):
            results = future.result()
            for res in results:
                processed += 1
                path = res["path"]
                print(f"\n[{processed}/{total_files}] {path.name}")

                if res.get("skipped"):
                    print(f"skipped {path.name}")
                    continue

                if res.get("success"):
                    successful += 1
                    orig = res["original_size"]
                    comp = res["compressed_size"]
                    total_original += orig
                    total_compressed += comp
                    reduction = (orig - comp) / orig * 100 if orig > 0 else 0
                    print(f"{path.name} | {fsz(orig)} → {fsz(comp)} ({reduction:.2f}%)")
                else:
                    print(f"Compression failed for {path}: {res.get('error')}")

    if total_original > 0 and successful > 0:
        savings = total_original - total_compressed
        savings_percent = (savings / total_original) * 100
        print(f"\nSpace saved: {fsz(savings)} ({savings_percent:.1f}%)")

    del dirs, files, batches
    gc.collect()

    after_total = gsz(target)
    dsz = abs(before_total - after_total)
    ratio = (dsz / before_total * 100) if before_total else 0.0
    cprint(f"total space saved: {fsz(dsz)} | {ratio:.2f}%")

    return 0


def handle_decompress(target: Path, args: Namespace, workers: int, chunk_size: int, before_total: int) -> int:
    files = list_files_decompress(target)

    if not files:
        print("No .zst files to decompress")
        return 0

    batch_size = max(1, min(10, len(files) // max(1, workers)))
    batches = [files[i : i + batch_size] for i in range(0, len(files), batch_size)]

    total_compressed = 0
    total_decompressed = 0
    successful = 0
    total_files = len(files)
    processed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        future_to_batch = {ex.submit(process_decompress_batch, batch, chunk_size): batch for batch in batches}

        for future in concurrent.futures.as_completed(future_to_batch):
            results = future.result()
            for res in results:
                processed += 1
                path = res["path"]
                dst = res.get("dst", path)
                print(f"\n[{processed}/{total_files}] {path.name}")

                if res.get("skipped"):
                    print(f"skipped {path.name}")
                    continue

                if res.get("success"):
                    successful += 1
                    orig = res["original_size"]
                    decomp = res["decompressed_size"]
                    total_compressed += orig
                    total_decompressed += decomp
                    expansion = (decomp - orig) / orig * 100 if orig > 0 else 0
                    print(f"{path.name} → {dst.name} | {fsz(orig)} → {fsz(decomp)} ({expansion:+.1f}%)")
                else:
                    print(f"Decompression failed for {path}: {res.get('error')}")

    if total_compressed > 0 and successful > 0:
        total_expansion = total_decompressed - total_compressed
        print(f"\nTotal expansion: {fsz(total_expansion)}")

    del files, batches
    gc.collect()

    after_total = gsz(target)
    dsz = abs(after_total - before_total)
    ratio = (dsz / before_total * 100) if before_total else 0.0
    if after_total > before_total:
        cprint(f"total space increased: {fsz(dsz)} | {ratio:.2f}%")
    else:
        cprint(f"total space decreased: {fsz(dsz)} | {ratio:.2f}%")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
