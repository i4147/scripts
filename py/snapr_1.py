import argparse
import multiprocessing
import shutil
import sys
import tarfile
from pathlib import Path
import cramjam
from loguru import logger

COMPRESSED_EXT = ".sn"
POOL_SIZE = 8


def compress_file(path, remove_original=True):
    try:
        compressed_path = path.with_suffix(path.suffix + COMPRESSED_EXT)
        with open(path, "rb") as f:
            data = f.read()
        compressed_data = bytes(cramjam.snappy.compress(data))
        with open(compressed_path, "wb") as f:
            f.write(compressed_data)
        if remove_original:
            path.unlink()
        original_size = len(data)
        compressed_size = len(compressed_data)
        ratio = (compressed_size / original_size * 100) if original_size > 0 else 0.0
        print(f"Compressed: {path} -> {compressed_path} ({original_size} -> {compressed_size} bytes, {ratio:.1f}%)")
        return True, f"Compressed {path.name}"
    except Exception as e:
        logger.error(f"Error compressing {path}: {e!s}")
        return False, str(e)


def decompress_file(path, remove_original=True):
    try:
        if path.suffix != COMPRESSED_EXT:
            return False, f"File {path} doesn't have {COMPRESSED_EXT} extension"
        output_path = path.with_suffix("")
        with open(path, "rb") as f:
            compressed_data = f.read()
        decompressed_data = bytes(cramjam.snappy.decompress(compressed_data))
        with open(output_path, "wb") as f:
            f.write(decompressed_data)
        if remove_original:
            path.unlink()
        print(f"Decompressed: {path} -> {output_path} ({len(compressed_data)} -> {len(decompressed_data)} bytes)")
        return True, f"Decompressed {path.name}"
    except Exception as e:
        logger.error(f"Error decompressing {path}: {e!s}")
        return False, str(e)


def process_file_worker(args):
    path, operation, remove_original = args
    if operation == "compress":
        return compress_file(path, remove_original)
    if operation == "decompress":
        return decompress_file(path, remove_original)
    return False, f"Unknown operation: {operation}"


def find_files(directory, operation, recursive=True):
    files = []
    if operation == "compress":
        pattern = "**/*" if recursive else "*"
        for path in directory.glob(pattern):
            if path.is_file() and path.suffix != COMPRESSED_EXT:
                files.append(path)
    else:
        pattern = f"**/*{COMPRESSED_EXT}" if recursive else f"*{COMPRESSED_EXT}"
        for path in directory.glob(pattern):
            if path.is_file():
                files.append(path)
    return files


def create_tar_archive(directory, remove_original=True):
    try:
        tar_path = directory.with_suffix(".tar")
        print(f"Creating tar archive: {tar_path}")
        with tarfile.open(tar_path, "w") as tar:
            tar.add(directory, arcname=directory.name)
        if remove_original:
            shutil.rmtree(directory)
            print(f"Removed original directory: {directory}")
        print(f"Created tar archive: {tar_path}")
        return tar_path
    except Exception as e:
        logger.error(f"Error creating tar archive for {directory}: {e!s}")
        return None


def tar_subdirectories(base_dir, remove_original=True):
    tar_files = []
    for item in base_dir.iterdir():
        if item.is_dir():
            tar_path = create_tar_archive(item, remove_original)
            if tar_path is not None:
                tar_files.append(tar_path)
    return tar_files


def process_files(
    paths,
    operation,
    remove_original=True,
):
    if not paths:
        logger.warning(f"No files found to {operation}")
        return 0, 0
    print(f"Processing {len(paths)} files with {POOL_SIZE} workers")
    success_count = 0
    failure_count = 0
    args_list = [(fp, operation, remove_original) for fp in paths]
    pool = multiprocessing.Pool(processes=POOL_SIZE)
    try:
        async_results = [(args[0], pool.apply_async(process_file_worker, (args,))) for args in args_list]
        for path, async_result in async_results:
            try:
                success, message = async_result.get()
                if success:
                    success_count += 1
                else:
                    failure_count += 1
                    logger.error(f"Failed to process {path}: {message}")
            except Exception as e:
                failure_count += 1
                logger.error(f"Error processing {path}: {e!s}")
    finally:
        pool.close()
        pool.join()
    return success_count, failure_count


def parse_args():
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
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")
    else:
        logger.remove()
        logger.add(sys.stderr, level="INFO")
    base_dir = Path(args.directory)
    if not base_dir.exists() or not base_dir.is_dir():
        logger.error(f"Directory not found: {base_dir}")
        return 1
    remove_original = not args.keep_original
    operation = "compress" if args.compress else "decompress"
    recursive = not args.no_recursive
    print(f"Starting {operation} operation on {base_dir}")
    print(f"Remove original: {remove_original}, Recursive: {recursive}")
    if args.tar and args.compress:
        print("Tarring subdirectories...")
        tar_files = tar_subdirectories(base_dir, remove_original)
        print(f"Created {len(tar_files)} tar archives")
    files_to_process = find_files(base_dir, operation, recursive)
    if not files_to_process:
        logger.warning(f"No files found to {operation}")
        return 0
    print(f"Found {len(files_to_process)} files to {operation}")
    success_count, failure_count = process_files(files_to_process, operation, remove_original)
    print(f"Completed {operation} operation")
    print(f"Success: {success_count}, Failed: {failure_count}")
    return 1 if failure_count > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
