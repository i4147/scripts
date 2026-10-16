import argparse
import asyncio
import mmap
import shutil
import sys
import tarfile
from multiprocessing import Pool
from pathlib import Path
import brotli
from loguru import logger

MAX_WORKERS = 8
CHUNK_SIZE = 524288
CHUNK_SIZE_SMALL = 32768
BROTLI_QUALITY = 11
BROTLI_LGWIN = 24
MIN_COMPRESS_SIZE = 1024
_POOL = None


def fsz(size):
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024.0 or unit == "TB":
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024.0
    return f"{value:.1f}TB"


def get_pool():
    global _POOL
    if _POOL is None:
        _POOL = Pool(processes=MAX_WORKERS)
    return _POOL


def compress_chunk(data):
    return brotli.compress(
        data,
        quality=BROTLI_QUALITY,
        lgwin=BROTLI_LGWIN,
        mode=brotli.MODE_GENERIC,
    )


def decompress_file(path):
    if path.suffix != ".br":
        return False
    out_path = path.with_suffix("")
    try:
        compressed_data = path.read_bytes()
        if not compressed_data:
            return False
        decompressed_data = brotli.decompress(compressed_data)
        out_path.write_bytes(decompressed_data)
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
        compressed = brotli.compress(
            data,
            quality=BROTLI_QUALITY,
            lgwin=BROTLI_LGWIN,
            mode=brotli.MODE_GENERIC,
        )
        outfile.write_bytes(compressed)
        return True
    except (OSError, MemoryError, brotli.error) as e:
        logger.error(f"Memory compression failed for {infile.name}: {e}")
        return False


def compress_chunked(in_path, out_path, file_size):
    try:
        chunk_count = (file_size + CHUNK_SIZE_SMALL - 1) // CHUNK_SIZE_SMALL
        pool = get_pool()
        with (
            out_path.open("wb", buffering=1024 * 1024) as fout,
            in_path.open("rb") as fin,
            mmap.mmap(fin.fileno(), length=0, access=mmap.ACCESS_READ) as mm,
        ):
            async_results = []
            for i in range(chunk_count):
                start = i * CHUNK_SIZE_SMALL
                end = min((i + 1) * CHUNK_SIZE_SMALL, file_size)
                chunk = mm[start:end]
                async_results.append(pool.apply_async(compress_chunk, (chunk,)))
            results = [None] * chunk_count
            for idx, ar in enumerate(async_results):
                try:
                    results[idx] = ar.get()
                except Exception as e:
                    logger.error(f"Chunk {idx} compression failed: {e}")
                    return False
            for compressed_chunk in results:
                if compressed_chunk:
                    fout.write(compressed_chunk)
                else:
                    return False
            return True
    except (OSError, MemoryError, brotli.error) as e:
        logger.error(f"Chunked compression failed for {in_path.name}: {e}")
        return False


def create_tar_archive(source_dir, output_path):
    try:
        with tarfile.open(output_path, "w") as tar:
            for item in source_dir.rglob("*"):
                if item.is_file():
                    arcname = item.relative_to(source_dir.parent)
                    tar.add(item, arcname=str(arcname))
        return True
    except Exception as e:
        logger.error(f"  Failed to create tar archive: {e}")
        return False


def compress_tar_to_br(tar_path, br_path):
    try:
        tar_size = tar_path.stat().st_size
        if tar_size < CHUNK_SIZE:
            success = compress_in_memory(tar_path, br_path)
        else:
            success = compress_chunked(tar_path, br_path, tar_size)
        if success and br_path.exists():
            br_size = br_path.stat().st_size
            if br_size == 0:
                logger.warning(f"Compressed archive empty for {tar_path.name}")
                br_path.unlink()
                return False
            if br_size < tar_size:
                tar_path.unlink()
                reduction = (tar_size - br_size) / tar_size * 100
                print(f"  ✓ Compressed archive: {reduction:.1f}% saved ({fsz(tar_size)} → {fsz(br_size)})")
                return True
            logger.warning("  ✗ Archive compression didn't save space, keeping .tar")
            br_path.unlink()
            return False
        return False
    except Exception as e:
        logger.error(f"  ✗ Failed to compress tar archive: {e}")
        return False


async def compress_folder_async(folder_path, output_base_name):
    loop = asyncio.get_running_loop()
    tar_path = Path(output_base_name + ".tar")
    br_path = Path(output_base_name + ".tar.br")
    try:
        print("  Creating tar archive...")
        success = await loop.run_in_executor(None, create_tar_archive, folder_path, tar_path)
        if not success or not tar_path.exists():
            logger.error("  Failed to create tar archive")
            return False
        print("  Compressing tar archive with Brotli (max quality)...")
        if compress_tar_to_br(tar_path, br_path):
            await loop.run_in_executor(None, shutil.rmtree, folder_path)
            return True
        return False
    except Exception as e:
        logger.error(f"Failed to compress folder {folder_path.name}: {e}")
        if tar_path.exists():
            tar_path.unlink()
        if br_path.exists():
            br_path.unlink()
        return False


def compress_file(path):
    out_path = path.with_suffix(path.suffix + ".br")
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
            print(f"  ✗ {path.name}: No space saved, removing compressed file")
            out_path.unlink()
            return False, 0, 0
        return False, 0, 0
    except (OSError, PermissionError, brotli.error) as e:
        logger.error(f"  ✗ Failed to compress {path.name}: {e}")
        return False, 0, 0


def should_compress(path):
    try:
        if not path.is_file() or path.is_symlink():
            return False
        compressed_extensions = (
            ".br",
            ".xz",
            ".gz",
            ".bz2",
            ".7z",
            ".zip",
            ".tar",
        )
        if path.suffix in compressed_extensions:
            return False
        size = path.stat().st_size
        return size >= MIN_COMPRESS_SIZE
    except (OSError, PermissionError):
        return False


def get_files(directory, mode="compress"):
    if mode == "compress":
        return [p for p in directory.glob("*") if p.is_file() and not p.is_symlink() and should_compress(p)]
    return [p for p in directory.glob("*.br") if p.is_file() and not p.is_symlink()]


def get_dirs(directory):
    return [p for p in directory.glob("*") if not p.is_symlink() and p.is_dir()]


def extract_tar_archive(tar_path, extract_dir):
    try:
        with tarfile.open(tar_path, "r") as tar:
            tar.extractall(path=extract_dir)
        return True
    except Exception as e:
        logger.error(f"  Failed to extract tar archive: {e}")
        return False


async def process_compress():
    cwd = Path.cwd()
    print("\n🔧 Brotli Compression Settings:")
    print(f"   Quality: {BROTLI_QUALITY}/11 (maximum)")
    print("   Window size: 16MB")
    print(f"   Workers: {MAX_WORKERS}")
    print(f"   Chunk size: {fsz(CHUNK_SIZE)}")
    dirs_to_compress = get_dirs(cwd)
    if dirs_to_compress:
        print(f"\n📁 Compressing {len(dirs_to_compress)} directories...")
        for dir_path in sorted(dirs_to_compress):
            relative_path = dir_path.relative_to(cwd)
            print(f"\n  Processing {relative_path}...")
            archive_path = str(dir_path.parent / dir_path.name)
            if await compress_folder_async(dir_path, archive_path):
                print(f"  ✓ Successfully compressed {relative_path} to {dir_path.name}.tar.br")
            else:
                logger.error(f"  ✗ Failed to compress {relative_path}")
    files_to_compress = get_files(cwd, mode="compress")
    if not files_to_compress:
        print("\n📄 No files to compress")
        return
    print(f"\n📄 Compressing {len(files_to_compress)} files with Brotli max compression...")
    total_original = 0
    total_compressed = 0
    successful = 0
    for i, path in enumerate(sorted(files_to_compress), 1):
        print(f"\n[{i}/{len(files_to_compress)}] {path.name}")
        success, orig_size, comp_size = compress_file(path)
        if success:
            successful += 1
            total_original += orig_size
            total_compressed += comp_size
    if successful > 0:
        savings = total_original - total_compressed
        savings_percent = savings / total_original * 100
        print(f"\n{'=' * 40}")
        print(f"✅ Compressed {successful}/{len(files_to_compress)} files")
        print(f"📊 Original size:  {fsz(total_original)}")
        print(f"📦 Compressed size: {fsz(total_compressed)}")
        print(f"💾 Space saved:    {fsz(savings)} ({savings_percent:.1f}%)")
        print(f"{'=' * 40}")
    elif files_to_compress:
        logger.error("\n❌ No files were successfully compressed")


async def process_decompress():
    cwd = Path.cwd()
    archives = [p for p in cwd.glob("*.tar.br") if p.is_file()]
    if archives:
        print(f"\n📦 Decompressing {len(archives)} archives...")
        for archive in sorted(archives):
            print(f"\n  Decompressing {archive.name}...")
            tar_path = None
            try:
                tar_path = archive.with_suffix("")
                print("    Decompressing Brotli...")
                compressed_data = archive.read_bytes()
                tar_data = brotli.decompress(compressed_data)
                tar_path.write_bytes(tar_data)
                extract_dir = archive.stem
                print(f"    Extracting tar to {extract_dir}/...")
                loop = asyncio.get_running_loop()
                success = await loop.run_in_executor(None, extract_tar_archive, tar_path, Path(extract_dir))
                if success:
                    tar_path.unlink()
                    archive.unlink()
                    print(f"  ✓ Extracted {archive.name} to {extract_dir}/")
                else:
                    logger.error(f"  ✗ Failed to extract {archive.name}")
            except Exception as e:
                logger.error(f"  ✗ Failed to decompress {archive.name}: {e}")
                if tar_path is not None and tar_path.exists():
                    tar_path.unlink()
    files_to_decompress = get_files(cwd, mode="decompress")
    if not files_to_decompress:
        print("\n📄 No .br files to decompress")
        return
    files_to_decompress = [p for p in files_to_decompress if p.suffixes != [".tar", ".br"]]
    if not files_to_decompress:
        return
    print(f"\n📄 Decompressing {len(files_to_decompress)} Brotli files...")
    total_original = 0
    total_decompressed = 0
    successful = 0
    for i, path in enumerate(sorted(files_to_decompress), 1):
        print(f"\n[{i}/{len(files_to_decompress)}] {path.name}")
        original_size = path.stat().st_size
        total_original += original_size
        if decompress_file(path):
            successful += 1
            out_path = path.with_suffix("")
            if out_path.exists():
                total_decompressed += out_path.stat().st_size
    if successful > 0:
        print(f"\n{'=' * 40}")
        print(f"✅ Decompressed {successful}/{len(files_to_decompress)} files")
        print(f"📦 Compressed size:   {fsz(total_original)}")
        print(f"📊 Decompressed size: {fsz(total_decompressed)}")
        print(f"{'=' * 40}")
    elif files_to_decompress:
        logger.error("\n❌ No files were successfully decompressed")


async def main_async(mode="compress"):
    if mode == "compress":
        await process_compress()
    elif mode == "decompress":
        await process_decompress()
    else:
        logger.error(f"Unknown mode: {mode}")


def shutdown_pool():
    global _POOL
    if _POOL is not None:
        _POOL.close()
        _POOL.join()
        _POOL = None


def main():
    parser = argparse.ArgumentParser(
        description="Multi-processed Brotli compression/decompression tool (max compression)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -c
  %(prog)s -d
  %(prog)s
Brotli Settings:
  - Quality: 11/11 (maximum compression)
  - Window size: 16MB (lgwin=24)
  - Mode: Generic
        """,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-c",
        "--compress",
        action="store_true",
        help="Compress files and folders with Brotli (default)",
    )
    group.add_argument(
        "-d",
        "--decompress",
        action="store_true",
        help="Decompress .br and .tar.br files",
    )
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
        shutdown_pool()


if __name__ == "__main__":
    raise SystemExit(main())
