from __future__ import annotations

import argparse
import contextlib
import fnmatch
import heapq
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import zstandard as zstd
from dh import fsz

SKIP_EXTENSIONS_COMPRESS = {
    ".xz",
    ".gz",
    ".7z",
    ".zip",
    ".whl",
    ".lz4",
    ".zst",
    ".br",
    ".bz2",
    ".lzma",
    ".z",
    ".rar",
    ".tar",
    ".tgz",
    ".tbz2",
    ".bz3",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".tiff",
    ".tif",
    ".webp",
    ".svg",
    ".ico",
    ".heic",
    ".heif",
    ".avif",
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".3gp",
    ".ogv",
    ".ts",
    ".m2ts",
    ".mp3",
    ".wav",
    ".flac",
    ".aac",
    ".ogg",
    ".wma",
    ".m4a",
    ".opus",
    ".mid",
    ".midi",
    ".aiff",
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".odt",
    ".ods",
    ".odp",
    ".epub",
    ".mobi",
    ".azw",
    ".azw3",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".iso",
    ".img",
    ".deb",
    ".rpm",
    ".pkg",
    ".msi",
}
VALID_DECOMPRESS_EXTENSIONS = {".zst"}
SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".bin",
    "bin",
    "dh",
    "print_persian",
    ".dist-info",
    ".egg-info",
    "zstandard",
}
SKIP_DIR_PATTERNS = ["*.egg-info", "*.dist-info"]


class SpaceStats:
    def __init__(self):
        self.original_size = 0
        self.compressed_size = 0
        self.lock = threading.Lock()

    def add(self, original: int, compressed: int):
        with self.lock:
            self.original_size += original
            self.compressed_size += compressed

    def get_savings(self):
        if self.original_size == 0:
            return 0, 0, 0
        saved = self.original_size - self.compressed_size
        ratio = self.compressed_size / self.original_size * 40 if self.original_size > 0 else 0
        percent_saved = saved / self.original_size * 40 if self.original_size > 0 else 0
        return saved, ratio, percent_saved


def should_skip_directory(dir_name: str) -> bool:
    if dir_name in SKIP_DIRS:
        return True
    return any(fnmatch.fnmatch(dir_name, pattern) for pattern in SKIP_DIR_PATTERNS)


def is_editable_package_dir(root_path: Path) -> bool:
    try:
        for item in root_path.iterdir():
            if item.is_dir() and item.name.endswith(".egg-info"):
                egg_info_path = item / "SOURCES.txt"
                if egg_info_path.exists():
                    return True
                direct_url = item / "direct_url.json"
                if direct_url.exists():
                    try:
                        with open(direct_url) as f:
                            data = json.load(f)
                            if data.get("dir_info", {}).get("editable", False):
                                return True
                    except:
                        pass
        return False
    except (PermissionError, OSError):
        return False


def get_files_generator(directory: Path, compress: bool):
    total_dirs = 0
    total_files = 0
    skipped_symlinks = 0
    skipped_extensions = 0
    skipped_editable = 0
    skipped_dirs = 0
    skipped_media = 0
    file_heap = []
    heap_size_limit = 10000
    for root, dirs, file_names in directory.walk():
        root_path = Path(root)
        if ".git" in root_path.parts:
            continue
        dirs_to_remove = []
        for dir_name in dirs:
            if should_skip_directory(dir_name):
                dirs_to_remove.append(dir_name)
                skipped_dirs += 1
        for dir_name in dirs_to_remove:
            dirs.remove(dir_name)
        if is_editable_package_dir(root_path):
            dirs.clear()
            skipped_editable += 1
            continue
        total_dirs += 1
        for file_name in file_names:
            file_path = root_path / file_name
            if file_path.is_symlink():
                skipped_symlinks += 1
                continue
            if ".egg-info" in str(file_path) or ".dist-info" in str(file_path):
                skipped_extensions += 1
                continue
            if compress:
                if file_path.suffix.lower() in SKIP_EXTENSIONS_COMPRESS:
                    skipped_extensions += 1
                    if file_path.suffix.lower() in {
                        ".jpg",
                        ".jpeg",
                        ".png",
                        ".gif",
                        ".bmp",
                        ".tiff",
                        ".tif",
                        ".webp",
                        ".svg",
                        ".ico",
                        ".heic",
                        ".heif",
                        ".avif",
                        ".mp4",
                        ".mkv",
                        ".avi",
                        ".mov",
                        ".wmv",
                        ".flv",
                        ".webm",
                        ".m4v",
                        ".mpg",
                        ".mpeg",
                        ".3gp",
                        ".ogv",
                        ".ts",
                        ".m2ts",
                        ".mp3",
                        ".wav",
                        ".flac",
                        ".aac",
                        ".ogg",
                        ".wma",
                        ".m4a",
                        ".opus",
                        ".mid",
                        ".midi",
                        ".aiff",
                        ".pdf",
                        ".docx",
                        ".pptx",
                        ".xlsx",
                        ".odt",
                        ".ods",
                        ".odp",
                        ".epub",
                        ".mobi",
                        ".azw",
                        ".azw3",
                    }:
                        skipped_media += 1
                    continue
            elif file_path.suffix not in VALID_DECOMPRESS_EXTENSIONS:
                skipped_extensions += 1
                continue
            try:
                file_size = file_path.stat().st_size
                heapq.heappush(file_heap, (-file_size, file_path))
                total_files += 1
            except (OSError, PermissionError):
                skipped_extensions += 1
                continue
            if len(file_heap) >= heap_size_limit:
                while file_heap:
                    neg_size, file_path = heapq.heappop(file_heap)
                    yield file_path
    if skipped_symlinks > 0:
        print(f"⚠️  Skipped {skipped_symlinks} symlinks")
    if skipped_media > 0:
        print(f"ℹ️  Skipped {skipped_media} media/binary files (already compressed)")
    if skipped_extensions > 0:
        print(f"ℹ️  Skipped {skipped_extensions} files with unwanted extensions")
    if skipped_editable > 0:
        print(f"ℹ️  Skipped {skipped_editable} editable package directories")
    if skipped_dirs > 0:
        print(f"ℹ️  Skipped {skipped_dirs} excluded directories")
    print(f"Sorting {total_files} files by size (largest first)...")
    while file_heap:
        _neg_size, file_path = heapq.heappop(file_heap)
        yield file_path
    print(f"Scanned {total_dirs} directories, found {total_files} files to process")


def compress_file(
    input_path: Path,
    output_path: Path,
    level: int = 3,
    threads: int = 4,
    remove_original: bool = False,
    stats: SpaceStats = None,
):
    try:
        original_size = input_path.stat().st_size
        compressor = zstd.ZstdCompressor(level=level, threads=threads)
        with open(input_path, "rb") as infile, open(output_path, "wb") as outfile:
            reader = compressor.stream_reader(infile)
            while True:
                chunk = reader.read(8192)
                if not chunk:
                    break
                outfile.write(chunk)
        compressed_size = output_path.stat().st_size
        if stats:
            stats.add(original_size, compressed_size)
        if remove_original:
            input_path.unlink()
        return True, input_path, output_path, original_size, compressed_size
    except Exception as e:
        if output_path.exists():
            with contextlib.suppress(BaseException):
                output_path.unlink()
        return False, input_path, str(e), 0, 0


def decompress_file(
    input_path: Path,
    output_path: Path,
    threads: int = 4,
    remove_original: bool = False,
    stats: SpaceStats = None,
):
    try:
        compressed_size = input_path.stat().st_size
        decompressor = zstd.ZstdDecompressor()
        with open(input_path, "rb") as infile, open(output_path, "wb") as outfile:
            reader = decompressor.stream_reader(infile)
            while True:
                chunk = reader.read(8192)
                if not chunk:
                    break
                outfile.write(chunk)
        decompressed_size = output_path.stat().st_size
        if remove_original:
            input_path.unlink()
        return (True, input_path, output_path, decompressed_size, compressed_size)
    except Exception as e:
        if output_path.exists():
            with contextlib.suppress(BaseException):
                output_path.unlink()
        return False, input_path, str(e), 0, 0


def process_files(
    file_generator,
    compress: bool,
    level: int = 3,
    threads: int = 4,
    remove_original: bool = False,
):
    stats = SpaceStats()
    failed = []
    skipped = 0
    completed = 0
    total_files = 0
    print(f"\n{'Compressing' if compress else 'Decompressing'} files...")
    print(f"Remove original files: {'Yes' if remove_original else 'No'}")
    print("-" * 40)
    files_list = list(file_generator)
    total_files = len(files_list)
    if total_files == 0:
        print("No files to process.")
        return
    print(f"Processing {total_files} files...")
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {}
        for file_path in files_list:
            if compress:
                output_path = file_path.with_suffix(file_path.suffix + ".zst")
                if output_path.exists():
                    print(f"⚠️  Skipping {file_path.name} - output already exists")
                    skipped += 1
                    completed += 1
                    continue
                future = executor.submit(
                    compress_file,
                    file_path,
                    output_path,
                    level,
                    threads,
                    remove_original,
                    stats,
                )
            else:
                output_path = file_path.with_suffix("")
                if output_path.exists():
                    print(f"⚠️  Skipping {file_path.name} - output already exists")
                    skipped += 1
                    completed += 1
                    continue
                future = executor.submit(
                    decompress_file,
                    file_path,
                    output_path,
                    threads,
                    remove_original,
                    stats,
                )
            futures[future] = file_path, output_path
        for future in as_completed(futures):
            result = future.result()
            if compress:
                success, path, output_path, _original_size, compressed_size = result
            else:
                success, path, output_path, _decompressed_size, _compressed_size = result
            completed += 1
            progress = int(completed / total_files * 40)
            bar = "█" * progress + "░" * (50 - progress)
            print(
                f"\rProgress: [{bar}] {completed}/{total_files} files",
                end="",
                flush=True,
            )
            if not success:
                failed.append((path, result[2] if len(result) > 2 else "Unknown error"))
    print("\n" + "-" * 40)
    if compress and total_files > 0:
        saved, ratio, percent_saved = stats.get_savings()
        print("\n📊 Compression Statistics:")
        print(f"   Original size:  {fsz(stats.original_size)}")
        print(f"   Compressed size: {fsz(stats.compressed_size)}")
        print(f"   Space saved:    {fsz(saved)} ({percent_saved:.1f}%)")
        print(f"   Compression ratio: {ratio:.1f}%")
    if skipped > 0:
        print(f"\n⚠️  Skipped {skipped} files (already exist or invalid format)")
    if failed:
        print(f"\n❌ Failed to process {len(failed)} files:")
        for path, error in failed:
            print(f"  - {path}: {error}")
    else:
        success_count = total_files - skipped
        if success_count > 0:
            print(f"""
✅ Successfully {"compressed" if compress else "decompressed"} {success_count} files!""")
            if remove_original:
                print("   Original files have been removed.")
        else:
            print("\n⚠️  No files were processed.")


def main():
    parser = argparse.ArgumentParser(description="Recursively compress or decompress files using Zstandard")
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument(
        "-c",
        "--compress",
        action="store_true",
        help="Compress files (default if no action specified)",
    )
    group.add_argument("-d", "--decompress", action="store_true", help="Decompress files")
    parser.add_argument(
        "--level",
        type=int,
        default=3,
        choices=range(1, 23),
        help="Compression level (1-22, default: 3)",
    )
    parser.add_argument("--threads", type=int, default=4, help="Number of threads to use (default: 4)")
    parser.add_argument(
        "--dir",
        type=str,
        default=".",
        help="Directory to process (default: current directory)",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep original files (default: remove on success)",
    )
    args = parser.parse_args()
    if not args.compress and not args.decompress:
        args.compress = True
        print("No action specified, defaulting to compression mode")
    if args.compress and (args.level < 1 or args.level > 22):
        print("Error: Compression level must be between 1 and 22")
        sys.exit(1)
    base_dir = Path(args.dir).resolve()
    if not base_dir.exists():
        print(f"Error: Directory '{base_dir}' does not exist")
        sys.exit(1)
    if not base_dir.is_dir():
        print(f"Error: '{base_dir}' is not a directory")
        sys.exit(1)
    remove_original = not args.keep
    print(f"Working directory: {base_dir}")
    print(f"Mode: {'Compression' if args.compress else 'Decompression'}")
    print(f"Threads: {args.threads}")
    if args.compress:
        print(f"Compression level: {args.level}")
    print(f"Keep original files: {'Yes' if args.keep else 'No'}")
    print("\nScanning directory tree...")
    file_generator = get_files_generator(base_dir, args.compress)
    process_files(file_generator, args.compress, args.level, args.threads, remove_original)


if __name__ == "__main__":
    raise SystemExit(main())
