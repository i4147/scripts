from __future__ import annotations

import argparse
import logging
import multiprocessing
import shutil
import sys
import tarfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

try:
    import cramjam
except ImportError:
    print("Error: cramjam library required. Install with: pip install cramjam")
    sys.exit(1)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
COMPRESSED_EXT = ".snappy"


def compress_file(file_path: Path, remove_original: bool = True) -> tuple[bool, str]:
    try:
        compressed_path = file_path.with_suffix(file_path.suffix + COMPRESSED_EXT)
        with open(file_path, "rb") as f:
            data = f.read()
        compressed_data = cramjam.snappy.compress(data)
        with open(compressed_path, "wb") as f:
            f.write(compressed_data)
        if remove_original:
            file_path.unlink()
        original_size = len(data)
        compressed_size = len(compressed_data)
        ratio = (compressed_size / original_size * 40) if original_size > 0 else 0
        logger.info(
            f"Compressed: {file_path} -> {compressed_path} ({original_size} -> {compressed_size} bytes, {ratio:.1f}%)"
        )
        return True, f"Compressed {file_path.name}"
    except Exception as e:
        logger.error(f"Error compressing {file_path}: {e!s}")
        return False, str(e)


def decompress_file(file_path: Path, remove_original: bool = True) -> tuple[bool, str]:
    try:
        if not file_path.suffix == COMPRESSED_EXT:
            return False, f"File {file_path} doesn't have {COMPRESSED_EXT} extension"
        original_suffix = file_path.suffixes[-2] if len(file_path.suffixes) > 1 else ""
        output_path = file_path.with_suffix("")
        with open(file_path, "rb") as f:
            compressed_data = f.read()
        decompressed_data = cramjam.snappy.decompress(compressed_data)
        with open(output_path, "wb") as f:
            f.write(decompressed_data)
        if remove_original:
            file_path.unlink()
        logger.info(
            f"Decompressed: {file_path} -> {output_path} ({len(compressed_data)} -> {len(decompressed_data)} bytes)"
        )
        return True, f"Decompressed {file_path.name}"
    except Exception as e:
        logger.error(f"Error decompressing {file_path}: {e!s}")
        return False, str(e)


def process_file_worker(args):
    file_path, operation, remove_original = args
    if operation == "compress":
        return compress_file(file_path, remove_original)
    elif operation == "decompress":
        return decompress_file(file_path, remove_original)
    else:
        return False, f"Unknown operation: {operation}"


def find_files(directory: Path, operation: str, recursive: bool = True) -> list[Path]:
    files = []
    if operation == "compress":
        for _ext in ["*"]:
            if recursive:
                pattern = "**/*"
            else:
                pattern = "*"
            for file_path in directory.glob(pattern):
                if file_path.is_file() and not file_path.suffix == COMPRESSED_EXT:
                    files.append(file_path)
    else:
        if recursive:
            pattern = f"**/*{COMPRESSED_EXT}"
        else:
            pattern = f"*{COMPRESSED_EXT}"
        for file_path in directory.glob(pattern):
            if file_path.is_file():
                files.append(file_path)
    return files


def create_tar_archive(directory: Path, remove_original: bool = True) -> Path | None:
    try:
        tar_path = directory.with_suffix(".tar")
        logger.info(f"Creating tar archive: {tar_path}")
        with tarfile.open(tar_path, "w") as tar:
            tar.add(directory, arcname=directory.name)
        if remove_original:
            shutil.rmtree(directory)
            logger.info(f"Removed original directory: {directory}")
        logger.info(f"Created tar archive: {tar_path}")
        return tar_path
    except Exception as e:
        logger.error(f"Error creating tar archive for {directory}: {e!s}")
        return None


def tar_subdirectories(base_dir: Path, remove_original: bool = True) -> list[Path]:
    tar_files = []
    for item in base_dir.iterdir():
        if item.is_dir():
            tar_path = create_tar_archive(item, remove_original)
            if tar_path:
                tar_files.append(tar_path)
    return tar_files


def process_files(
    file_paths: list[Path],
    operation: str,
    remove_original: bool = True,
    max_workers: int | None = None,
) -> tuple[int, int]:
    if not file_paths:
        logger.warning(f"No files found to {operation}")
        return 0, 0
    if max_workers is None:
        max_workers = min(multiprocessing.cpu_count(), len(file_paths))
    logger.info(f"Processing {len(file_paths)} files with {max_workers} workers")
    success_count = 0
    failure_count = 0
    args_list = [(fp, operation, remove_original) for fp in file_paths]
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {executor.submit(process_file_worker, args): args[0] for args in args_list}
        for future in as_completed(future_to_file):
            file_path = future_to_file[future]
            try:
                success, message = future.result()
                if success:
                    success_count += 1
                else:
                    failure_count += 1
                    logger.error(f"Failed to process {file_path}: {message}")
            except Exception as e:
                failure_count += 1
                logger.error(f"Error processing {file_path}: {e!s}")
    return success_count, failure_count


def main():
    parser = argparse.ArgumentParser(
        description="Compress or decompress files recursively using Snappy (cramjam)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python snappy_tool.py -c .
  python snappy_tool.py -d /path/to/directory
  python snappy_tool.py -c -t .
  python snappy_tool.py -c --keep-original .
        """,
    )
    parser.add_argument("directory", type=str, help="Directory to process")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-c", "--compress", action="store_true", help="Compress files")
    group.add_argument("-d", "--decompress", action="store_true", help="Decompress files")
    parser.add_argument(
        "-t",
        "--tar",
        action="store_true",
        help="Tar subdirectories first before compression",
    )
    parser.add_argument(
        "--keep-original",
        action="store_true",
        help="Keep original files (default: remove them)",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Do not process subdirectories recursively",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of worker processes (default: CPU count)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    base_dir = Path(args.directory)
    if not base_dir.exists() or not base_dir.is_dir():
        logger.error(f"Directory not found: {base_dir}")
        sys.exit(1)
    remove_original = not args.keep_original
    operation = "compress" if args.compress else "decompress"
    recursive = not args.no_recursive
    logger.info(f"Starting {operation} operation on {base_dir}")
    logger.info(f"Remove original: {remove_original}, Recursive: {recursive}")
    if args.tar and args.compress:
        logger.info("Tarring subdirectories...")
        tar_files = tar_subdirectories(base_dir, remove_original)
        logger.info(f"Created {len(tar_files)} tar archives")
    files_to_process = find_files(base_dir, operation, recursive)
    if not files_to_process:
        logger.warning(f"No files found to {operation}")
        sys.exit(0)
    logger.info(f"Found {len(files_to_process)} files to {operation}")
    success_count, failure_count = process_files(files_to_process, operation, remove_original, args.workers)
    logger.info(f"Completed {operation} operation")
    logger.info(f"Success: {success_count}, Failed: {failure_count}")
    if failure_count > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
