import argparse
import io
import tarfile
from multiprocessing import Pool
from pathlib import Path
from typing import List
import pylzma
from loguru import logger

POOL_WORKERS = 8

DEFAULT_COMPRESS_OUTPUT = "./compressed"
DEFAULT_DECOMPRESS_OUTPUT = "./decompressed"


def create_tar_for_directory(dir_path):
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
        tar.add(str(dir_path), arcname=dir_path.name)
    return tar_buffer.getvalue()


def compress_file(
    path,
    output_dir,
    tar_subdirs_first=False,
):
    try:
        path = Path(path)
        if path.is_dir():
            if tar_subdirs_first:
                tar_data = create_tar_for_directory(path)
                compressed_data = pylzma.compress(tar_data)
                output_file = output_dir / f"{path.name}.tar.7z"
            else:
                return None
        else:
            with open(path, "rb") as f:
                data = f.read()
            compressed_data = pylzma.compress(data)
            output_file = output_dir / f"{path.name}.7z"
        with open(output_file, "wb") as f:
            f.write(compressed_data)
        return f"Compressed: {path} -> {output_file}"
    except Exception as e:
        return f"Error compressing {path}: {e!s}"


def decompress_file(path, output_dir):
    try:
        path = Path(path)
        with open(path, "rb") as f:
            compressed_data = f.read()
        decompressed_data = pylzma.decompress(compressed_data)
        if path.suffixes == [".tar", ".7z"]:
            output_name = path.name.replace(".tar.7z", "")
            tar_buffer = io.BytesIO(decompressed_data)
            with tarfile.open(fileobj=tar_buffer, mode="r") as tar:
                tar.extractall(path=str(output_dir))
            return f"Decompressed: {path} -> {output_dir}/{output_name}"
        elif path.suffix == ".7z":
            output_name = path.name.replace(".7z", "")
            output_file = output_dir / output_name
            with open(output_file, "wb") as f:
                f.write(decompressed_data)
            return f"Decompressed: {path} -> {output_file}"
        else:
            return f"Skipped (not a .7z or .tar.7z file): {path}"
    except Exception as e:
        return f"Error decompressing {path}: {e!s}"


def process_files_parallel(
    files,
    output_dir,
    mode,
    tar_subdirs_first=False,
):
    results = []
    tasks = []
    if mode == "compress":
        for file in files:
            tasks.append(((file, output_dir, tar_subdirs_first), "compress"))
    else:
        for file in files:
            tasks.append(((file, output_dir), "decompress"))
    with Pool(processes=POOL_WORKERS) as pool:
        async_results = []
        for args, task_mode in tasks:
            if task_mode == "compress":
                async_results.append(pool.apply_async(compress_file, args=args))
            else:
                async_results.append(pool.apply_async(decompress_file, args=args))
        for async_result in async_results:
            result = async_result.get()
            if result:
                results.append(result)
                print(result)
    return results


def _default_output_for_mode(mode):
    if mode == "decompress":
        return DEFAULT_DECOMPRESS_OUTPUT
    return DEFAULT_COMPRESS_OUTPUT


def build_parser():
    parser = argparse.ArgumentParser(
        description=("Compress/decompress files recursively using pylzma with parallel processing")
    )
    parser.add_argument(
        "-c",
        "--compress",
        action="store_const",
        const="compress",
        dest="mode",
        default="compress",
        help="Compress files (default mode)",
    )
    parser.add_argument(
        "-d",
        "--decompress",
        action="store_const",
        const="decompress",
        dest="mode",
        help="Decompress files",
    )
    parser.add_argument(
        "-t",
        "--tar-subdirs-first",
        action="store_true",
        default=False,
        help="Tar subdirectories first before compression",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help=("Output directory (default: ./compressed for compress, ./decompressed for decompress)"),
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    mode = args.mode
    tar_subdirs_first = args.tar_subdirs_first
    output_arg = args.output
    output_dir = Path(output_arg if output_arg is not None else _default_output_for_mode(mode))
    current_dir = Path(".")
    if mode == "compress":
        output_dir.mkdir(exist_ok=True)
        all_files = []
        for item in current_dir.rglob("*"):
            if item.is_file() or (item.is_dir() and not tar_subdirs_first):
                try:
                    if output_dir in item.parents or item == output_dir:
                        continue
                except (ValueError, AttributeError):
                    pass
                if item.is_file():
                    if item.suffix == ".7z":
                        continue
                    all_files.append(item)
                elif item.is_dir() and tar_subdirs_first:
                    if item != current_dir:
                        try:
                            if output_dir not in item.parents and item != output_dir:
                                all_files.append(item)
                        except (ValueError, AttributeError):
                            all_files.append(item)
        if not all_files:
            logger.warning("No files found to compress in current directory")
            return 0
        print(f"Found {len(all_files)} items to compress")
        print(f"Compressing to: {output_dir}")
        process_files_parallel(all_files, output_dir, "compress", tar_subdirs_first)
    else:
        output_dir.mkdir(exist_ok=True)
        compressed_files = []
        for item in current_dir.rglob("*"):
            if item.is_file() and (item.suffix == ".7z" or item.name.endswith(".tar.7z")):
                try:
                    if output_dir not in item.parents and item != output_dir:
                        compressed_files.append(item)
                except (ValueError, AttributeError):
                    compressed_files.append(item)
        if not compressed_files:
            logger.warning("No .7z or .tar.7z files found in current directory")
            return 0
        print(f"Found {len(compressed_files)} files to decompress")
        print(f"Decompressing to: {output_dir}")
        process_files_parallel(compressed_files, output_dir, "decompress", False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
