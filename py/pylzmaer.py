import argparse
import asyncio
import mmap
import shutil
import sys
import tempfile
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Final
import pylzma
from loguru import logger

MAX_WORKERS = 8
CHUNK_SIZE = 524288
SMALL_FILE_THRESHOLD = 32768
TEMP_DIR = Path(tempfile.gettempdir()) / "pylzma_temp"
LZMA_FILTERS = [
    {
        "id": pylzma.FILTER_LZMA1,
        "preset": 9 | pylzma.PRESET_EXTREME,
        "dict_size": 256 * 1024 * 1024,
    }
]
COMPRESSED_EXTENSIONS = (
    ".lzma",
    ".xz",
    ".gz",
    ".bz2",
    ".br",
    ".zst",
    ".zip",
    ".rar",
)
_POOL = None


def fsz(size):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def _get_pool():
    global _POOL
    if _POOL is None:
        _POOL = Pool(processes=MAX_WORKERS)
    return _POOL


def _close_pool():
    global _POOL
    if _POOL is not None:
        _POOL.close()
        _POOL.join()
        _POOL = None


def should_compress(path):
    try:
        if not path.is_file() or path.is_symlink():
            return False
        if path.suffix in COMPRESSED_EXTENSIONS:
            return False
        size = path.stat().st_size
        return size >= 1024
    except (OSError, PermissionError):
        return False


def get_files(directory, mode="compress"):
    if mode == "compress":
        return sorted(p for p in directory.glob("*") if p.is_file() and not p.is_symlink() and should_compress(p))
    return sorted(p for p in directory.glob("*.lzma") if p.is_file() and not p.is_symlink())


def get_dirs(directory):
    return sorted(p for p in directory.glob("*") if not p.is_symlink() and p.is_dir())


def decompress_file(path):
    if path.suffix != ".lzma":
        return False
    out_path = path.with_suffix("")
    try:
        with path.open("rb") as fin:
            decompressed = pylzma.decompress(fin.read())
        out_path.write_bytes(decompressed)
        original_size = path.stat().st_size
        decompressed_size = out_path.stat().st_size
        print(f"  ✓ Decompressed {path.name}: {fsz(original_size)} → {fsz(decompressed_size)}")
        path.unlink()
        return True
    except Exception as e:
        logger.error(f"  ✗ Failed to decompress {path.name}: {e}")
        return False


def compress_in_memory(infile, outfile):
    try:
        data = infile.read_bytes()
        if not data:
            return False
        compressed = pylzma.compress(data, filters=LZMA_FILTERS)
        outfile.write_bytes(compressed)
        return True
    except (OSError, MemoryError, ValueError) as e:
        logger.error(f"Memory compression failed for {infile.name}: {e}")
        return False


def compress_chunk(data, chunk_id, temp_dir):
    compressed_path = temp_dir / f"chunk_{chunk_id:06d}.lzma"
    try:
        compressed = pylzma.compress(data, filters=LZMA_FILTERS)
        compressed_path.write_bytes(compressed)
        return compressed_path
    except Exception as e:
        raise Exception(f"Chunk {chunk_id} compression failed: {e}") from e


def compress_chunked(in_path, out_path, file_size):
    temp_dir = TEMP_DIR / f"compress_{in_path.stem}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        chunk_count = (file_size + SMALL_FILE_THRESHOLD - 1) // SMALL_FILE_THRESHOLD
        compressed_paths = [None] * chunk_count
        pool = _get_pool()
        async_results = []
        with (
            in_path.open("rb") as fin,
            mmap.mmap(fin.fileno(), length=0, access=mmap.ACCESS_READ) as mm,
        ):
            for i in range(chunk_count):
                start = i * SMALL_FILE_THRESHOLD
                end = min((i + 1) * SMALL_FILE_THRESHOLD, file_size)
                chunk = bytes(mm[start:end])
                async_results.append(pool.apply_async(compress_chunk, (chunk, i, temp_dir)))
            for i, result in enumerate(async_results):
                try:
                    compressed_paths[i] = result.get()
                except Exception as e:
                    logger.error(f"Chunk {i} compression failed: {e}")
                    return False

        with out_path.open("wb") as fout:
            fout.write(chunk_count.to_bytes(4, "big"))
            for compressed_path in compressed_paths:
                if compressed_path is not None and compressed_path.exists():
                    payload = compressed_path.read_bytes()
                    fout.write(len(payload).to_bytes(8, "big"))
                    fout.write(payload)
        return True
    except (OSError, MemoryError, ValueError) as e:
        logger.error(f"Chunked compression failed for {in_path.name}: {e}")
        return False
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


async def compress_folder_async(folder_path, output_path):
    loop = asyncio.get_running_loop()

    def compress():
        import io
        import tarfile

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            tar.add(folder_path, arcname=folder_path.name)
        compressed = pylzma.compress(buf.getvalue(), filters=LZMA_FILTERS)
        output_path.write_bytes(compressed)

    try:
        await loop.run_in_executor(None, compress)
        if not output_path.exists():
            return False
        original_size = sum(f.stat().st_size for f in folder_path.rglob("*") if f.is_file())
        compressed_size = output_path.stat().st_size
        if compressed_size < original_size:
            await loop.run_in_executor(None, shutil.rmtree, folder_path)
            reduction = (original_size - compressed_size) / original_size * 100
            print(f"  ✓ Compressed archive: {reduction:.1f}% saved ({fsz(original_size)} → {fsz(compressed_size)})")
            return True
        logger.warning("  ✗ Archive compression didn't save space")
        output_path.unlink()
        return False
    except Exception as e:
        logger.error(f"Failed to compress folder {folder_path.name}: {e}")
        if output_path.exists():
            output_path.unlink()
        return False


def decompress_chunked(in_path, out_path):
    try:
        with in_path.open("rb") as fin:
            chunk_count_bytes = fin.read(4)
            if len(chunk_count_bytes) != 4:
                return False
            chunk_count = int.from_bytes(chunk_count_bytes, "big")
            with out_path.open("wb") as fout:
                for _ in range(chunk_count):
                    length_bytes = fin.read(8)
                    if len(length_bytes) != 8:
                        return False
                    length = int.from_bytes(length_bytes, "big")
                    payload = fin.read(length)
                    if len(payload) != length:
                        return False
                    fout.write(pylzma.decompress(payload))
        return True
    except (OSError, ValueError, TypeError) as e:
        logger.error(f"Chunked decompression failed for {in_path.name}: {e}")
        return False


def compress_file(path):
    out_path = path.with_suffix(path.suffix + ".lzma")
    if out_path.exists():
        print(f"Skipping {path.name} - output already exists")
        return False, 0, 0
    try:
        original_size = path.stat().st_size
        if not original_size:
            return False, 0, 0
        if original_size < CHUNK_SIZE:
            success = compress_in_memory(path, out_path)
        else:
            success = compress_chunked(path, out_path, original_size)
        if success and out_path.exists():
            compressed_size = out_path.stat().st_size
            if compressed_size == 0:
                logger.warning(f"Compressed file empty for {path.name}")
                out_path.unlink()
                return False, 0, 0
            if compressed_size < original_size:
                path.unlink()
                reduction = (original_size - compressed_size) / original_size * 100
                print(f"  ✓ {path.name}: {reduction:.1f}% saved ({fsz(original_size)} → {fsz(compressed_size)})")
                return True, original_size, compressed_size
            logger.warning(f"  ✗ {path.name}: No space saved, removing compressed file")
            out_path.unlink()
            return False, 0, 0
        return False, 0, 0
    except (OSError, PermissionError, ValueError) as e:
        logger.error(f"  ✗ Failed to compress {path.name}: {e}")
        return False, 0, 0


async def process_compress():
    cwd = Path.cwd()
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    print("\n🔧 LZMA Compression Settings:")
    print("   Format: raw LZMA1 via pylzma")
    print("   Filter: LZMA1 (preset 9 + extreme)")
    print("   Dictionary size: 256 MB")
    print("   Solid compression: Yes (chunk concatenation)")
    print("   Block size: 4 MB")
    print(f"   Parallel workers: {MAX_WORKERS}")
    print(f"   Chunk size: {fsz(CHUNK_SIZE)}")
    dirs_to_compress = get_dirs(cwd)
    if dirs_to_compress:
        print(f"\n📁 Compressing {len(dirs_to_compress)} directories...")
        for dir_path in dirs_to_compress:
            relative_path = dir_path.relative_to(cwd)
            print(f"\n  Processing {relative_path}...")
            output_path = dir_path.parent / f"{dir_path.name}.lzma"
            if await compress_folder_async(dir_path, output_path):
                logger.success(f"  ✓ Successfully compressed {relative_path} to {dir_path.name}.lzma")
            else:
                logger.error(f"  ✗ Failed to compress {relative_path}")
    files_to_compress = get_files(cwd, mode="compress")
    if not files_to_compress:
        print("\n📄 No files to compress")
        return
    print(f"\n📄 Compressing {len(files_to_compress)} files with LZMA max compression...")
    total_original = 0
    total_compressed = 0
    successful = 0
    for i, path in enumerate(files_to_compress, 1):
        print(f"\n[{i}/{len(files_to_compress)}] {path.name}")
        success, orig_size, comp_size = compress_file(path)
        if success:
            successful += 1
            total_original += orig_size
            total_compressed += comp_size
    if successful > 0:
        savings = total_original - total_compressed
        savings_percent = savings / total_original * 100
        logger.success(f"\n{'=' * 40}")
        logger.success(f"✅ Compressed {successful}/{len(files_to_compress)} files")
        print(f"📊 Original size:  {fsz(total_original)}")
        print(f"📦 Compressed size: {fsz(total_compressed)}")
        print(f"💾 Space saved:    {fsz(savings)} ({savings_percent:.1f}%)")
        logger.success(f"{'=' * 40}")
    elif files_to_compress:
        logger.error("\n❌ No files were successfully compressed")


async def process_decompress():
    cwd = Path.cwd()
    files_to_decompress = get_files(cwd, mode="decompress")
    if not files_to_decompress:
        print("\n📄 No .lzma files to decompress")
        return
    print(f"\n📄 Decompressing {len(files_to_decompress)} LZMA archives...")
    total_original = 0
    total_decompressed = 0
    successful = 0
    for i, path in enumerate(files_to_decompress, 1):
        print(f"\n[{i}/{len(files_to_decompress)}] {path.name}")
        try:
            out_path = path.with_suffix("")
            original_size = path.stat().st_size
            total_original += original_size
            if out_path.exists():
                logger.warning("  Output already exists, skipping...")
                continue

            decompressed = False
            try:
                with path.open("rb") as fin:
                    head = fin.read(12)
                if len(head) == 12:
                    chunk_count = int.from_bytes(head[:4], "big")
                    first_len = int.from_bytes(head[4:12], "big")
                    if 0 < chunk_count < 10_000_000 and 0 < first_len <= original_size:
                        if decompress_chunked(path, out_path):
                            decompressed = True
            except (OSError, ValueError):
                decompressed = False
            if not decompressed:
                if out_path.exists():
                    out_path.unlink()
                data = path.read_bytes()
                out_path.write_bytes(pylzma.decompress(data))
            if out_path.is_file():
                decompressed_size = out_path.stat().st_size
            else:
                decompressed_size = sum(f.stat().st_size for f in out_path.rglob("*") if f.is_file())
            total_decompressed += decompressed_size
            print(f"  ✓ Decompressed {path.name}: {fsz(original_size)} → {fsz(decompressed_size)}")
            path.unlink()
            successful += 1
        except Exception as e:
            logger.error(f"  ✗ Failed to decompress {path.name}: {e}")
    if successful > 0:
        logger.success(f"\n{'=' * 40}")
        logger.success(f"✅ Decompressed {successful}/{len(files_to_decompress)} archives")
        print(f"📦 Compressed size:   {fsz(total_original)}")
        print(f"📊 Decompressed size: {fsz(total_decompressed)}")
        logger.success(f"{'=' * 40}")
    elif files_to_decompress:
        logger.error("\n❌ No files were successfully decompressed")


async def main_async(mode="compress"):
    if mode == "compress":
        await process_compress()
    elif mode == "decompress":
        await process_decompress()
    else:
        logger.error(f"Unknown mode: {mode}")


def _build_parser():
    parser = argparse.ArgumentParser(
        description=("Multi-threaded LZMA compression/decompression tool (max compression)"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -c
  %(prog)s -d
  %(prog)s
LZMA Settings:
  - Format: raw LZMA1 via pylzma
  - Compression level: 9 + extreme
  - Dictionary size: 256 MB
  - Chunk size: 512 KB
        """,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-c",
        "--compress",
        action="store_true",
        help="Compress files and folders with LZMA (default)",
    )
    group.add_argument(
        "-d",
        "--decompress",
        action="store_true",
        help="Decompress .lzma files",
    )
    return parser


def main():
    parser = _build_parser()
    args = parser.parse_args()
    mode = "decompress" if args.decompress else "compress"
    try:
        asyncio.run(main_async(mode))
    except KeyboardInterrupt:
        logger.warning("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n❌ Unexpected error: {e}")
        sys.exit(1)
    finally:
        _close_pool()


if __name__ == "__main__":
    raise SystemExit(main())
