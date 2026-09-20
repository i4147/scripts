import argparse
import textwrap
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final
import lzma_mt
from loguru import logger
ARCHIVE_EXTENSIONS = {
    ".zip",
    ".br",
    ".xz",
    ".gz",
    ".bz2",
    ".bz3",
    ".zst",
    ".7z",
    ".lz4",
    ".rar",
    ".tar",
    ".tgz",
    ".tbz",
    ".tbz2",
    ".z",
    ".lz",
    ".lzma",
    ".xza",
}
EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    ".env",
    "node_modules",
}
NUM_WORKERS = 8
def should_exclude(path):
    return any(part in EXCLUDE_DIRS for part in path.parts)
def get_files_to_process(root_dir, compress):
    files = []
    if compress:
        for file in root_dir.rglob("*"):
            if file.is_file() and not should_exclude(file):
                if file.suffix.lower() not in ARCHIVE_EXTENSIONS:
                    files.append(file)
    else:
        for file in root_dir.rglob("*"):
            if (
                file.is_file()
                and not should_exclude(file)
                and file.suffix.lower() == ".xz"
            ):
                files.append(file)
    return sorted(files)
def compress_file(
    path,
    preset=9,
    threads=4,
    remove_orig=True,
):
    try:
        with open(path, "rb") as f:
            data = f.read()
        compressed = lzma_mt.compress(data, preset=preset, threads=threads)
        output_path = path.parent / (path.name + ".xz")
        with open(output_path, "wb") as f:
            f.write(compressed)
        if remove_orig:
            path.unlink()
        return path, True, f"Compressed to {output_path.name}"
    except Exception as e:
        return path, False, f"Error: {e!s}"
def decompress_file(
    path,
    remove_orig=True,
):
    try:
        if path.suffix.lower() != ".xz":
            return path, False, "Error: Not an .xz file"
        with open(path, "rb") as f:
            data = f.read()
        decompressed = lzma_mt.decompress(data)
        output_path = path.parent / path.stem
        with open(output_path, "wb") as f:
            f.write(decompressed)
        if remove_orig:
            path.unlink()
        return path, True, f"Decompressed to {output_path.name}"
    except Exception as e:
        return path, False, f"Error: {e!s}"
def _process_files_impl(
    root_dir,
    compress,
    preset,
    threads,
    remove_orig,
):
    files = get_files_to_process(root_dir, compress)
    if not files:
        action = "compress" if compress else "decompress"
        print(f"No files found to {action}")
        return
    action = "Compressing" if compress else "Decompressing"
    print(f"{action} {len(files)} files with {NUM_WORKERS} workers...")
    print(f"Preset: {preset}, Threads: {threads}")
    total_success = 0
    total_failed = 0
    total = len(files)
    with Pool(processes=NUM_WORKERS) as pool:
        results = []
        if compress:
            for file in files:
                results.append(
                    pool.apply_async(
                        compress_file, (file, preset, threads, remove_orig)
                    )
                )
        else:
            for file in files:
                results.append(pool.apply_async(decompress_file, (file, remove_orig)))
        completed = 0
        for result in results:
            path, success, message = result.get()
            completed += 1
            pct = completed / total * 40
            print(f"[{pct:5.1f}%] {completed}/{total}")
            if success:
                total_success += 1
                status = "✓"
            else:
                total_failed += 1
                status = "✗"
            rel_path = path.relative_to(root_dir)
            print(f"{status} {rel_path}: {message}")
    print("─" * 40)
    print(f"Total successful: {total_success}")
    print(f"Total failed: {total_failed}")
def process_files(
    root_dir,
    compress,
    preset,
    threads,
    remove_orig=True,
):
    _process_files_impl(root_dir, compress, preset, threads, remove_orig)
def main():
    parser = argparse.ArgumentParser(
        description="Compress or decompress files using lzma_mt with parallel processing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              python compress_files.py
              python compress_files.py -c --preset 6 --threads 8
              python compress_files.py -d /path/to/files
              python compress_files.py -c /path/to/files
        """),
    )
    parser.add_argument(
        "-c",
        "--compress",
        action="store_true",
        help="Compress files (default if no -d specified)",
    )
    parser.add_argument(
        "-d",
        "--decompress",
        action="store_true",
        help="Decompress .xz files",
    )
    parser.add_argument(
        "--preset",
        type=int,
        default=9,
        choices=range(10),
        help="Compression preset 0-9 (default: 9)",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=4,
        help="Threads per compression job (default: 4)",
    )
    parser.add_argument(
        "--keep-orig",
        action="store_true",
        help="Keep original files after compression/decompression",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to process (default: current directory)",
    )
    args = parser.parse_args()
    if args.compress and args.decompress:
        logger.error("Cannot specify both -c and -d")
        return 1
    compress_mode = args.compress or not args.decompress
    root_dir = Path(args.directory).resolve()
    if not root_dir.is_dir():
        logger.error(f"{root_dir} is not a directory")
        return 1
    process_files(
        root_dir,
        compress=compress_mode,
        preset=args.preset,
        threads=args.threads,
        remove_orig=not args.keep_orig,
    )
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
