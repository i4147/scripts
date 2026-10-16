from __future__ import annotations

import argparse
import gzip
import shutil
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path

from dh import fsz


class CompressionStats:
    def __init__(self):
        self.total_files = 0
        self.successful = 0
        self.failed = 0
        self.total_original_size = 0
        self.total_compressed_size = 0

    def add_success(self, original_size: int, compressed_size: int):
        self.total_files += 1
        self.successful += 1
        self.total_original_size += original_size
        self.total_compressed_size += compressed_size

    def add_failure(self):
        self.total_files += 1
        self.failed += 1


def compress_file(file_path: Path) -> tuple[Path, bool, int, int, str]:
    gz_path = file_path.with_suffix(file_path.suffix + ".gz")
    try:
        original_size = file_path.stat().st_size
        with (
            open(file_path, "rb") as f_in,
            gzip.open(gz_path, "wb", compresslevel=9) as f_out,
        ):
            shutil.copyfileobj(f_in, f_out)
        compressed_size = gz_path.stat().st_size
        file_path.unlink()
        return (file_path, True, original_size, compressed_size, "")
    except Exception as e:
        if gz_path.exists():
            gz_path.unlink()
        return (file_path, False, 0, 0, str(e))


def find_files_to_compress(directories: list[Path], skip_extensions: set | None = None) -> list[Path]:
    if skip_extensions is None:
        skip_extensions = {".gz", ".zip", ".bz2", ".xz", ".7z", ".rar", ".tar"}
    files_to_compress = []
    for directory in directories:
        if not directory.exists():
            print(f"⚠ Warning: Directory '{directory}' does not exist, skipping...")
            continue
        for file_path in directory.rglob("*"):
            if file_path.is_file() and file_path.suffix not in skip_extensions:
                if not file_path.suffix.endswith(".gz"):
                    files_to_compress.append(file_path)
    return files_to_compress


def format_ratio(original: int, compressed: int) -> str:
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
  %(prog)s --workers 8 dir1
        """,
    )
    parser.add_argument(
        "directories",
        nargs="*",
        default=["."],
        help="Directories to process (default: current directory)",
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=None,
        help="Number of worker processes (default: CPU count)",
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
    print("\n" + "=" * 42)
    print("🔍 GZIP Compression Tool (Maximum Compression - Level 9)".center(70))
    print("-" * 42)
    print("\n📂 Processing directories:")
    for d in directories:
        print(f"   • {d}")
    skip_extensions = {".gz", ".zip", ".bz2", ".xz", ".7z", ".rar", ".tar"}
    if args.exclude:
        for ext in args.exclude:
            if not ext.startswith("."):
                ext = "." + ext
            skip_extensions.add(ext)
        print(f"\n🚫 Excluding extensions: {', '.join(sorted(skip_extensions))}")
    print("\n🔎 Scanning for files...")
    start_time = time.time()
    files_to_compress = find_files_to_compress(directories, skip_extensions)
    if not files_to_compress:
        print("\n✅ No files found to compress!")
        return
    print(f"📊 Found {len(files_to_compress)} file(s) to compress\n")
    print("-" * 42)
    print(f"{'File':<50} {'Original':>10} {'Compressed':>10} {'Ratio':>8} {'Status':>10}")
    print("-" * 42)
    stats = CompressionStats()
    max_workers = args.workers
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {executor.submit(compress_file, file_path): file_path for file_path in files_to_compress}
        for future in as_completed(future_to_file):
            file_path, success, orig_size, comp_size, error = future.result()
            try:
                rel_path = file_path.relative_to(Path.cwd())
            except ValueError:
                rel_path = file_path
            display_path = str(rel_path)
            if len(display_path) > 47:
                display_path = "..." + display_path[-44:]
            if success:
                stats.add_success(orig_size, comp_size)
                status_symbol = "✅"
                print(
                    f"{display_path:<50} {fsz(orig_size):>10} {fsz(comp_size):>10} {format_ratio(orig_size, comp_size):>8} {status_symbol:>10}"
                )
            else:
                stats.add_failure()
                status_symbol = "❌"
                print(f"{display_path:<50} {'N/A':>10} {'N/A':>10} {'N/A':>8} {status_symbol:>10}")
                if error:
                    print(f"   ⚠ Error: {error}")
    elapsed_time = time.time() - start_time
    print("\n" + "=" * 42)
    print("📊 COMPRESSION SUMMARY".center(70))
    print("-" * 42)
    print(f"  Total files processed:     {stats.total_files}")
    print(f"  Successfully compressed:   {stats.successful} ✅")
    print(f"  Failed compressions:       {stats.failed} ❌")
    print(f"  Original total size:       {fsz(stats.total_original_size)}")
    print(f"  Compressed total size:     {fsz(stats.total_compressed_size)}")
    if stats.total_original_size > 0:
        overall_ratio = (1 - stats.total_compressed_size / stats.total_original_size) * 100
        space_saved = stats.total_original_size - stats.total_compressed_size
        print(f"  Overall compression ratio: {overall_ratio:.1f}%")
        print(f"  Space saved:               {fsz(space_saved)}")
    print(f"  Time elapsed:               {timedelta(seconds=int(elapsed_time))}")
    print("-" * 42)


if __name__ == "__main__":
    main()
