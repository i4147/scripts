import argparse
import os
import shutil
import sys
import tarfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import zstandard as zstd

SKIP_DIRS = frozenset({"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"})


def get_dir_size(path):
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file():
            total += entry.stat().st_size
    return total


def compress_directory(subdir):
    subdir = Path(subdir)
    tar_zst_path = subdir.parent / f"{subdir.name}.tar.zst"
    try:
        original_size = get_dir_size(subdir)
        cctx = zstd.ZstdCompressor(level=19)
        with open(tar_zst_path, "wb") as f_out:
            with cctx.stream_writer(f_out) as compressor:
                with tarfile.open(fileobj=compressor, mode="w|") as tar:
                    tar.add(subdir, arcname=subdir.name)
        if not tar_zst_path.exists() or tar_zst_path.stat().st_size == 0:
            raise Exception("Archive creation failed or empty")
        shutil.rmtree(subdir)
        compressed_size = tar_zst_path.stat().st_size
        space_freed = original_size - compressed_size
        return {
            "success": True,
            "name": subdir.name,
            "original_size": original_size,
            "compressed_size": compressed_size,
            "space_freed": space_freed,
        }
    except Exception as e:
        return {"success": False, "name": subdir.name, "error": str(e)}


def decompress_archive(archive_path):
    archive_path = Path(archive_path)
    try:
        archive_size = archive_path.stat().st_size
        dctx = zstd.ZstdDecompressor()
        with open(archive_path, "rb") as f_in:
            with dctx.stream_reader(f_in) as decompressor:
                with tarfile.open(fileobj=decompressor, mode="r|") as tar:
                    tar.extractall(path=archive_path.parent)
        archive_path.unlink()
        dir_name = archive_path.stem
        extracted_dir = archive_path.parent / dir_name
        extracted_size = get_dir_size(extracted_dir)
        space_used = extracted_size - archive_size
        return {
            "success": True,
            "name": archive_path.name,
            "archive_size": archive_size,
            "extracted_size": extracted_size,
            "space_used": space_used,
        }
    except Exception as e:
        return {"success": False, "name": archive_path.name, "error": str(e)}


def format_size(size_bytes):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def main():
    parser = argparse.ArgumentParser(description="Compress/decompress subdirectories with tar+zstd")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "-c",
        "--compress",
        action="store_true",
        help="Compress subdirectories to .tar.zst",
    )
    group.add_argument(
        "-d",
        "--decompress",
        action="store_true",
        help="Decompress .tar.zst files back to directories",
    )
    args = parser.parse_args()
    current_dir = Path(".")
    if args.compress:
        subdirs = [d for d in current_dir.iterdir() if d.is_dir()]
        if not subdirs:
            print("No subdirectories found to compress.")
            return
        print(f"Found {len(subdirs)} subdirectories to compress.")
        print("Starting compression with zstd level 9...")
        total_original = 0
        total_compressed = 0
        successful = 0
        failed = 0
        with ProcessPoolExecutor(max_workers=os.cpu_count()) as executor:
            future_to_dir = {executor.submit(compress_directory, subdir): subdir for subdir in subdirs}
            for future in as_completed(future_to_dir):
                result = future.result()
                if result["success"]:
                    successful += 1
                    total_original += result["original_size"]
                    total_compressed += result["compressed_size"]
                    print(
                        f"✓ {result['name']}: {format_size(result['original_size'])} -> {format_size(result['compressed_size'])} (freed {format_size(result['space_freed'])})"
                    )
                else:
                    failed += 1
                    print(f"✗ {result['name']}: Failed - {result['error']}")
        print(f"\n{'=' * 60}")
        print(f"Compression complete: {successful} successful, {failed} failed")
        if successful > 0:
            total_freed = total_original - total_compressed
            compression_ratio = (1 - total_compressed / total_original) * 100
            print(f"Total original size:   {format_size(total_original)}")
            print(f"Total compressed size: {format_size(total_compressed)}")
            print(f"Total space freed:     {format_size(total_freed)}")
            print(f"Compression ratio:     {compression_ratio:.1f}%")
    elif args.decompress:
        archives = list(current_dir.glob("*.tar.zst"))
        if not archives:
            print("No .tar.zst files found to decompress.")
            return
        print(f"Found {len(archives)} archives to decompress.")
        print("Starting decompression...")
        total_archive = 0
        total_extracted = 0
        successful = 0
        failed = 0
        with ProcessPoolExecutor(max_workers=os.cpu_count()) as executor:
            future_to_archive = {executor.submit(decompress_archive, archive): archive for archive in archives}
            for future in as_completed(future_to_archive):
                result = future.result()
                if result["success"]:
                    successful += 1
                    total_archive += result["archive_size"]
                    total_extracted += result["extracted_size"]
                    space_change = result["space_used"]
                    if space_change >= 0:
                        change_str = f"(space used: +{format_size(space_change)})"
                    else:
                        change_str = f"(space freed: {format_size(-space_change)})"
                    print(
                        f"✓ {result['name']}: {format_size(result['archive_size'])} -> {format_size(result['extracted_size'])} {change_str}"
                    )
                else:
                    failed += 1
                    print(f"✗ {result['name']}: Failed - {result['error']}")
        print(f"\n{'=' * 60}")
        print(f"Decompression complete: {successful} successful, {failed} failed")
        if successful > 0:
            total_change = total_extracted - total_archive
            print(f"Total archive size:     {format_size(total_archive)}")
            print(f"Total extracted size:   {format_size(total_extracted)}")
            print(f"Net space change:       {format_size(total_change)}")


if __name__ == "__main__":
    try:
        import zstandard
    except ImportError:
        print("Error: zstandard package is required. Install it with: pip install zstandard")
        sys.exit(1)
    main()
