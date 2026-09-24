import argparse
import gzip
import time
from datetime import timedelta
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Final
from dh import fsz
from loguru import logger

BUFFER_SIZE = 256 * 1024
WORKERS = 8
DEFAULT_SKIP_EXTENSIONS = {
    ".gz",
    ".zip",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".tar",
}


class CompressionStats:
    def __init__(self):
        self.total_files = 0
        self.successful = 0
        self.failed = 0
        self.total_original_size = 0
        self.total_compressed_size = 0

    def add_success(self, original_size, compressed_size):
        self.total_files += 1
        self.successful += 1
        self.total_original_size += original_size
        self.total_compressed_size += compressed_size

    def add_failure(self):
        self.total_files += 1
        self.failed += 1


def stream_copy(src_file, dst_file, chunk_size=BUFFER_SIZE):
    while True:
        chunk = src_file.read(chunk_size)
        if not chunk:
            break
        dst_file.write(chunk)


def compress_file(path):
    gz_path = path.with_suffix(path.suffix + ".gz")
    try:
        original_size = path.stat().st_size
        with (
            open(path, "rb") as f_in,
            gzip.open(gz_path, "wb", compresslevel=9) as f_out,
        ):
            stream_copy(f_in, f_out)
        compressed_size = gz_path.stat().st_size
        path.unlink()
        return (path, True, original_size, compressed_size, "")
    except Exception as e:
        if gz_path.exists():
            gz_path.unlink()
        return (path, False, 0, 0, str(e))


def find_files_to_compress(directories, skip_extensions=None):
    if skip_extensions is None:
        skip_extensions = set(DEFAULT_SKIP_EXTENSIONS)
    files_to_compress = []
    for directory in directories:
        if not directory.exists():
            logger.warning("Directory '{}' does not exist, skipping...", directory)
            continue
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix not in skip_extensions:
                files_to_compress.append(path)
    return files_to_compress


def format_ratio(original, compressed):
    if original == 0:
        return "N/A"
    ratio = (1 - compressed / original) * 100
    return f"{ratio:.1f}%"


def main():
    parser = argparse.ArgumentParser(
        description="Compress files recursively with gzip (maximum compression)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s
  %(prog)s dir1 dir2
  %(prog)s /path/to/dir1 /path/to/dir2
        """,
    )
    parser.add_argument(
        "directories",
        nargs="*",
        default=["."],
        help="Directories to process (default: current directory)",
    )
    parser.add_argument(
        "--exclude",
        "-e",
        nargs="+",
        default=[],
        help="Additional file extensions to exclude (e.g., .pdf .jpg)",
    )
    args = parser.parse_args()
    directories = [Path(d).resolve() for d in args.directories]
    print("=" * 40)
    print("🔍 GZIP Compression Tool (Maximum Compression - Level 9)".center(70))
    print("-" * 40)
    print("📂 Processing directories:")
    for d in directories:
        print("   • {}", d)
    skip_extensions = set(DEFAULT_SKIP_EXTENSIONS)
    if args.exclude:
        for ext in args.exclude:
            if not ext.startswith("."):
                ext = "." + ext
            skip_extensions.add(ext)
        print("🚫 Excluding extensions: {}", ", ".join(sorted(skip_extensions)))
    print("🔎 Scanning for files...")
    start_time = time.time()
    files_to_compress = find_files_to_compress(directories, skip_extensions)
    if not files_to_compress:
        logger.success("✅ No files found to compress!")
        return 0
    print("📊 Found {} file(s) to compress", len(files_to_compress))
    print("-" * 40)
    print(f"{'File':<50} {'Original':>10} {'Compressed':>10} {'Ratio':>8} {'Status':>10}")
    print("-" * 40)
    stats = CompressionStats()
    with Pool(processes=WORKERS) as pool:
        async_results = [pool.apply_async(compress_file, (path,)) for path in files_to_compress]
        for async_result in async_results:
            path, success, orig_size, comp_size, error = async_result.get()
            try:
                rel_path = path.relative_to(Path.cwd())
            except ValueError:
                rel_path = path
            display_path = str(rel_path)
            if len(display_path) > 47:
                display_path = "..." + display_path[-44:]
            if success:
                stats.add_success(orig_size, comp_size)
                status_symbol = "✅"
                print(
                    f"{display_path:<50} {fsz(orig_size):>10} "
                    f"{fsz(comp_size):>10} "
                    f"{format_ratio(orig_size, comp_size):>8} "
                    f"{status_symbol:>10}"
                )
            else:
                stats.add_failure()
                status_symbol = "❌"
                print(f"{display_path:<50} {'N/A':>10} {'N/A':>10} {'N/A':>8} {status_symbol:>10}")
                if error:
                    logger.warning("   ⚠ Error: {}", error)
    elapsed_time = time.time() - start_time
    print("=" * 40)
    print("📊 COMPRESSION SUMMARY".center(70))
    print("-" * 40)
    print("  Total files processed:     {}", stats.total_files)
    print("  Successfully compressed:   {} ✅", stats.successful)
    print("  Failed compressions:       {} ❌", stats.failed)
    print("  Original total size:       {}", fsz(stats.total_original_size))
    print("  Compressed total size:     {}", fsz(stats.total_compressed_size))
    if stats.total_original_size > 0:
        overall_ratio = (1 - stats.total_compressed_size / stats.total_original_size) * 100
        space_saved = stats.total_original_size - stats.total_compressed_size
        print("  Overall compression ratio: {:.1f}%", overall_ratio)
        print("  Space saved:               {}", fsz(space_saved))
    print(
        "  Time elapsed:               {}",
        timedelta(seconds=int(elapsed_time)),
    )
    print("-" * 40)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
