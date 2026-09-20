from __future__ import annotations

import argparse
import contextlib
import fnmatch
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
        ratio = self.compressed_size / self.original_size * 40
        percent_saved = saved / self.original_size * 40
        return saved, ratio, percent_saved


def should_skip_directory(dir_name: str) -> bool:
    if dir_name in SKIP_DIRS:
        return True
    return any(fnmatch.fnmatch(dir_name, pattern) for pattern in SKIP_DIR_PATTERNS)


def is_editable_package_dir(root_path: Path) -> bool:
    try:
        for item in root_path.iterdir():
            if item.is_dir() and item.name.endswith(".egg-info"):
                if (item / "SOURCES.txt").exists():
                    return True
                direct_url = item / "direct_url.json"
                if direct_url.exists():
                    try:
                        import json

                        with open(direct_url) as f:
                            data = json.load(f)
                            if data.get("dir_info", {}).get("editable", False):
                                return True
                    except:
                        pass
        return False
    except (PermissionError, OSError):
        return False


def walk_files(directory: Path, compress: bool):
    stats = {
        "dirs": 0,
        "files": 0,
        "skipped_symlinks": 0,
        "skipped_extensions": 0,
        "skipped_editable": 0,
        "skipped_dirs": 0,
        "skipped_media": 0,
    }
    media_extensions = {
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
    }
    for root, dirs, files in directory.walk():
        root_path = Path(root)
        if ".git" in root_path.parts:
            continue
        dirs_to_remove = []
        for dir_name in dirs:
            if should_skip_directory(dir_name):
                dirs_to_remove.append(dir_name)
                stats["skipped_dirs"] += 1
        for dir_name in dirs_to_remove:
            dirs.remove(dir_name)
        if is_editable_package_dir(root_path):
            dirs.clear()
            stats["skipped_editable"] += 1
            continue
        stats["dirs"] += 1
        for file_name in files:
            file_path = root_path / file_name
            if file_path.is_symlink():
                stats["skipped_symlinks"] += 1
                continue
            if ".egg-info" in str(file_path) or ".dist-info" in str(file_path):
                stats["skipped_extensions"] += 1
                continue
            if compress:
                if file_path.suffix.lower() in SKIP_EXTENSIONS_COMPRESS:
                    stats["skipped_extensions"] += 1
                    if file_path.suffix.lower() in media_extensions:
                        stats["skipped_media"] += 1
                    continue
            elif file_path.suffix not in VALID_DECOMPRESS_EXTENSIONS:
                stats["skipped_extensions"] += 1
                continue
            stats["files"] += 1
            yield file_path
    if stats["skipped_symlinks"] > 0:
        print(f"⚠️  Skipped {stats['skipped_symlinks']} symlinks")
    if stats["skipped_media"] > 0:
        print(f"ℹ️  Skipped {stats['skipped_media']} media/binary files (already compressed)")
    if stats["skipped_extensions"] > 0:
        print(f"ℹ️  Skipped {stats['skipped_extensions']} files with unwanted extensions")
    if stats["skipped_editable"] > 0:
        print(f"ℹ️  Skipped {stats['skipped_editable']} editable package directories")
    if stats["skipped_dirs"] > 0:
        print(f"ℹ️  Skipped {stats['skipped_dirs']} excluded directories")
    print(f"Scanned {stats['dirs']} directories, found {stats['files']} files to process")


def compress_file(
    input_path: Path,
    output_path: Path,
    level: int,
    threads: int,
    remove_original: bool,
    stats: SpaceStats,
):
    try:
        original_size = input_path.stat().st_size
        compressor = zstd.ZstdCompressor(level=level, threads=threads)
        with open(input_path, "rb") as infile, open(output_path, "wb") as outfile:
            reader = compressor.stream_reader(infile)
            outfile.writelines(iter(lambda: reader.read(8192), b""))
        compressed_size = output_path.stat().st_size
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
    threads: int,
    remove_original: bool,
    stats: SpaceStats,
):
    try:
        compressed_size = input_path.stat().st_size
        decompressor = zstd.ZstdDecompressor()
        with open(input_path, "rb") as infile, open(output_path, "wb") as outfile:
            reader = decompressor.stream_reader(infile)
            outfile.writelines(iter(lambda: reader.read(8192), b""))
        decompressed_size = output_path.stat().st_size
        stats.add(decompressed_size, compressed_size)
        if remove_original:
            input_path.unlink()
        return (True, input_path, output_path, decompressed_size, compressed_size)
    except Exception as e:
        if output_path.exists():
            with contextlib.suppress(BaseException):
                output_path.unlink()
        return False, input_path, str(e), 0, 0


def process_files(file_generator, compress: bool, level: int, threads: int, remove_original: bool):
    stats = SpaceStats()
    failed = []
    skipped = 0
    processed = 0
    total = 0
    print("\nCounting files...")
    files_list = list(file_generator)
    total = len(files_list)
    if total == 0:
        print("No files to process.")
        return
    print(f"\n{'Compressing' if compress else 'Decompressing'} {total} files...")
    print(f"Remove original files: {'Yes' if remove_original else 'No'}")
    print("-" * 40)
    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {}
        for file_path in files_list:
            if compress:
                output_path = file_path.with_suffix(file_path.suffix + ".zst")
                if output_path.exists():
                    print(f"⚠️  Skipping {file_path.name} - output already exists")
                    skipped += 1
                    processed += 1
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
                    processed += 1
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
            processed += 1
            progress = int(processed / total * 40)
            bar = "█" * progress + "░" * (50 - progress)
            print(f"\rProgress: [{bar}] {processed}/{total} files", end="", flush=True)
            if not result[0]:
                failed.append((result[1], result[2]))
    print("\n" + "-" * 40)
    if compress and total > 0:
        saved, ratio, percent_saved = stats.get_savings()
        print("\n📊 Compression Statistics:")
        print(f"   Original size:   {fsz(stats.original_size)}")
        print(f"   Compressed size: {fsz(stats.compressed_size)}")
        print(f"   Space saved:     {fsz(saved)} ({percent_saved:.1f}%)")
        print(f"   Compression ratio: {ratio:.1f}%")
    if skipped > 0:
        print(f"\n⚠️  Skipped {skipped} files")
    if failed:
        print(f"\n❌ Failed to process {len(failed)} files:")
        for path, error in failed[:10]:
            print(f"  - {path}: {error}")
        if len(failed) > 10:
            print(f"  ... and {len(failed) - 10} more errors")
    else:
        success_count = total - skipped
        if success_count > 0:
            print(f"""
✅ Successfully {"compressed" if compress else "decompressed"} {success_count} files!""")
            if remove_original:
                print("   Original files have been removed.")


def main():
    parser = argparse.ArgumentParser(description="Recursively compress or decompress files using Zstandard")
    action_group = parser.add_mutually_exclusive_group(required=False)
    action_group.add_argument("-c", "--compress", action="store_true", help="Compress files (default)")
    action_group.add_argument("-d", "--decompress", action="store_true", help="Decompress files")
    parser.add_argument(
        "--level",
        type=int,
        default=3,
        choices=range(1, 23),
        help="Compression level (1-22, default: 3)",
    )
    parser.add_argument("--threads", type=int, default=4, help="Number of threads (default: 4)")
    parser.add_argument("--dir", type=str, default=".", help="Directory to process (default: current)")
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep original files (default: remove on success)",
    )
    args = parser.parse_args()
    if not args.compress and not args.decompress:
        args.compress = True
        print("No action specified, defaulting to compression mode")
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
    file_generator = walk_files(base_dir, args.compress)
    process_files(file_generator, args.compress, args.level, args.threads, remove_original)


if __name__ == "__main__":
    raise SystemExit(main())
