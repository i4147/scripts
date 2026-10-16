import argparse
import asyncio
import mmap
import shutil
import sys
import tempfile
from multiprocessing import Pool
from pathlib import Path
import py7zr
from loguru import logger

MAX_WORKERS = 8
CHUNK_SIZE = 524288
SMALL_FILE_THRESHOLD = 32768
TEMP_DIR = Path(tempfile.gettempdir()) / "py7zr_temp"
SEVENZ_SETTINGS = {
    "filters": [{"id": py7zr.FILTER_LZMA2, "preset": 9}],
    "dictionary_size": 256 * 1024 * 1024,
    "solid": True,
    "header_compression": True,
    "block_size": 4 * 1024 * 1024,
}
COMPRESSED_EXTENSIONS = (
    ".7z",
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
    return sorted(p for p in directory.glob("*.7z") if p.is_file() and not p.is_symlink())


def get_dirs(directory):
    return sorted(p for p in directory.glob("*") if not p.is_symlink() and p.is_dir())


def decompress_file(path):
    if path.suffix != ".7z":
        return False
    out_path = path.with_suffix("")
    try:
        with (
            py7zr.SevenZipFile(path, mode="r") as sevenz,
            tempfile.TemporaryDirectory() as tmpdir,
        ):
            sevenz.extractall(path=tmpdir)
            extracted = Path(tmpdir) / out_path.name
            if extracted.exists():
                shutil.move(str(extracted), str(out_path))
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
        with tempfile.NamedTemporaryFile(delete=False, suffix=".7z") as tmp:
            tmp_path = Path(tmp.name)
        try:
            with py7zr.SevenZipFile(
                tmp_path,
                mode="w",
                filters=SEVENZ_SETTINGS["filters"],
                dictionary_size=SEVENZ_SETTINGS["dictionary_size"],
                solid=SEVENZ_SETTINGS["solid"],
                header_compression=SEVENZ_SETTINGS["header_compression"],
            ) as sevenz:
                sevenz.write(infile, arcname=infile.name)
            compressed = tmp_path.read_bytes()
            outfile.write_bytes(compressed)
            return True
        finally:
            tmp_path.unlink(missing_ok=True)
    except (OSError, MemoryError, py7zr.Bad7zFile) as e:
        logger.error(f"Memory compression failed for {infile.name}: {e}")
        return False


def compress_chunk(data, chunk_id, temp_dir):
    chunk_path = temp_dir / f"chunk_{chunk_id:06d}.bin"
    compressed_path = temp_dir / f"chunk_{chunk_id:06d}.7z"
    try:
        chunk_path.write_bytes(data)
        with py7zr.SevenZipFile(
            compressed_path,
            mode="w",
            filters=SEVENZ_SETTINGS["filters"],
            dictionary_size=SEVENZ_SETTINGS["dictionary_size"],
            solid=SEVENZ_SETTINGS["solid"],
            header_compression=SEVENZ_SETTINGS["header_compression"],
        ) as sevenz:
            sevenz.write(chunk_path, arcname=chunk_path.name)
        return compressed_path
    except Exception as e:
        raise Exception(f"Chunk {chunk_id} compression failed: {e}") from e
    finally:
        if chunk_path.exists():
            chunk_path.unlink()


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
                chunk = mm[start:end]
                async_results.append(pool.apply_async(compress_chunk, (chunk, i, temp_dir)))
            for i, result in enumerate(async_results):
                try:
                    compressed_paths[i] = result.get()
                except Exception as e:
                    logger.error(f"Chunk {i} compression failed: {e}")
                    return False
        with py7zr.SevenZipFile(
            out_path,
            mode="w",
            filters=SEVENZ_SETTINGS["filters"],
            dictionary_size=SEVENZ_SETTINGS["dictionary_size"],
            solid=SEVENZ_SETTINGS["solid"],
            header_compression=SEVENZ_SETTINGS["header_compression"],
        ) as sevenz:
            for compressed_path in compressed_paths:
                if compressed_path is not None and compressed_path.exists():
                    sevenz.write(compressed_path, arcname=compressed_path.name)
        return True
    except (OSError, MemoryError, py7zr.Bad7zFile) as e:
        logger.error(f"Chunked compression failed for {in_path.name}: {e}")
        return False
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


async def compress_folder_async(folder_path, output_path):
    loop = asyncio.get_running_loop()

    def compress():
        with py7zr.SevenZipFile(
            output_path,
            mode="w",
            filters=SEVENZ_SETTINGS["filters"],
            dictionary_size=SEVENZ_SETTINGS["dictionary_size"],
            solid=SEVENZ_SETTINGS["solid"],
            header_compression=SEVENZ_SETTINGS["header_compression"],
            recursive=True,
        ) as sevenz:
            sevenz.writeall(folder_path, arcname=folder_path.name)

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


def compress_file(path):
    out_path = path.with_suffix(path.suffix + ".7z")
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
    except (OSError, PermissionError, py7zr.Bad7zFile) as e:
        logger.error(f"  ✗ Failed to compress {path.name}: {e}")
        return False, 0, 0


async def process_compress():
    cwd = Path.cwd()
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    print("\n🔧 7-Zip Compression Settings:")
    print("   Format: 7z")
    print("   Filter: LZMA2 (preset 9 - maximum)")
    print("   Dictionary size: 256 MB")
    print("   Solid compression: Yes")
    print("   Header compression: Yes")
    print("   Block size: 4 MB")
    print(f"   Parallel workers: {MAX_WORKERS}")
    print(f"   Chunk size: {fsz(CHUNK_SIZE)}")
    dirs_to_compress = get_dirs(cwd)
    if dirs_to_compress:
        print(f"\n📁 Compressing {len(dirs_to_compress)} directories...")
        for dir_path in dirs_to_compress:
            relative_path = dir_path.relative_to(cwd)
            print(f"\n  Processing {relative_path}...")
            output_path = dir_path.parent / f"{dir_path.name}.7z"
            if await compress_folder_async(dir_path, output_path):
                logger.success(f"  ✓ Successfully compressed {relative_path} to {dir_path.name}.7z")
            else:
                logger.error(f"  ✗ Failed to compress {relative_path}")
    files_to_compress = get_files(cwd, mode="compress")
    if not files_to_compress:
        print("\n📄 No files to compress")
        return
    print(f"\n📄 Compressing {len(files_to_compress)} files with 7-Zip max compression...")
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
        print("\n📄 No .7z files to decompress")
        return
    print(f"\n📄 Decompressing {len(files_to_decompress)} 7-Zip archives...")
    total_original = 0
    total_decompressed = 0
    successful = 0
    for i, path in enumerate(files_to_decompress, 1):
        print(f"\n[{i}/{len(files_to_decompress)}] {path.name}")
        try:
            with py7zr.SevenZipFile(path, mode="r") as sevenz:
                out_path = path.with_suffix("")
                original_size = path.stat().st_size
                total_original += original_size
                if out_path.exists():
                    logger.warning("  Output already exists, skipping...")
                    continue
                sevenz.extractall(path=out_path)
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
        description=("Multi-threaded 7-Zip compression/decompression tool (max compression)"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -c
  %(prog)s -d
  %(prog)s
7-Zip Settings:
  - Format: 7z with LZMA2
  - Compression level: 9 (maximum)
  - Dictionary size: 256 MB
  - Solid compression: Enabled
  - Header compression: Enabled
        """,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-c",
        "--compress",
        action="store_true",
        help="Compress files and folders with 7-Zip (default)",
    )
    group.add_argument(
        "-d",
        "--decompress",
        action="store_true",
        help="Decompress .7z files",
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
