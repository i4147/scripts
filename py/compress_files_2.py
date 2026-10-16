from __future__ import annotations

import argparse
import sys
import textwrap
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import lzma_mt

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
    ".Z",
    ".lz",
    ".lzma",
    ".xza",
}
MEDIA_EXTENSIONS = {
    ".mkv",
    ".mp4",
    ".webm",
    ".avi",
    ".mov",
    ".flv",
    ".wmv",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".mp3",
    ".aac",
    ".flac",
    ".wav",
    ".m4a",
    ".opus",
    ".ogg",
    ".wma",
    ".alac",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".webp",
    ".svg",
    ".tiff",
    ".ico",
    ".heic",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".iso",
    ".img",
}
EXCLUDE_DIRS = {".git", "__pycache__", ".venv", "venv", ".env", "node_modules"}


def should_exclude(path: Path) -> bool:
    return any(part in EXCLUDE_DIRS for part in path.parts)


def is_media_file(path: Path) -> bool:
    return path.suffix.lower() in MEDIA_EXTENSIONS


def get_files_to_process(root_dir: Path, compress: bool) -> list[Path]:
    files = []
    if compress:
        for file in root_dir.rglob("*"):
            if file.is_file() and not should_exclude(file):
                if file.suffix.lower() not in ARCHIVE_EXTENSIONS and not is_media_file(file):
                    files.append(file)
    else:
        for file in root_dir.rglob("*"):
            if file.is_file() and not should_exclude(file) and file.suffix.lower() == ".xz":
                files.append(file)
    return sorted(files)


def compress_file(
    filepath: Path, preset: int = 9, threads: int = 4, remove_orig: bool = True
) -> tuple[Path, bool, str, int, int]:
    try:
        with open(filepath, "rb") as f:
            data = f.read()
        original_size = len(data)
        compressed = lzma_mt.compress(data, preset=preset, threads=threads)
        len(compressed)
        output_path = filepath.parent / (filepath.name + ".xz")
        with open(output_path, "wb") as f:
            f.write(compressed)
        space_freed = 0
        if remove_orig:
            filepath.unlink()
            space_freed = original_size
        return (
            filepath,
            True,
            f"Compressed to {output_path.name}",
            original_size,
            space_freed,
        )
    except Exception as e:
        return filepath, False, f"Error: {e!s}", 0, 0


def decompress_file(filepath: Path, remove_orig: bool = True) -> tuple[Path, bool, str, int, int]:
    try:
        if filepath.suffix.lower() != ".xz":
            return filepath, False, "Error: Not an .xz file", 0, 0
        with open(filepath, "rb") as f:
            data = f.read()
        compressed_size = len(data)
        decompressed = lzma_mt.decompress(data)
        output_path = filepath.parent / filepath.stem
        with open(output_path, "wb") as f:
            f.write(decompressed)
        space_freed = 0
        if remove_orig:
            filepath.unlink()
            space_freed = compressed_size
        return (
            filepath,
            True,
            f"Decompressed to {output_path.name}",
            compressed_size,
            space_freed,
        )
    except Exception as e:
        return filepath, False, f"Error: {e!s}", 0, 0


def format_bytes(bytes_val: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_val < 1024.0:
            return f"{bytes_val:.2f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.2f} PB"


def process_files(
    root_dir: Path,
    compress: bool,
    preset: int,
    threads: int,
    num_workers: int,
    remove_orig: bool = True,
):
    files = get_files_to_process(root_dir, compress)
    if not files:
        action = "compress" if compress else "decompress"
        print(f"No files found to {action}")
        return
    action = "Compressing" if compress else "Decompressing"
    print(f"{action} {len(files)} files with {num_workers} workers...")
    print(f"Preset: {preset}, Threads: {threads}")
    print()
    total_success = 0
    total_failed = 0
    total_space_freed = 0
    total_original_size = 0
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        if compress:
            futures = {executor.submit(compress_file, file, preset, threads, remove_orig): file for file in files}
        else:
            futures = {executor.submit(decompress_file, file, remove_orig): file for file in files}
        completed = 0
        for future in as_completed(futures):
            completed += 1
            filepath, success, message, orig_size, space_freed = future.result()
            pct = completed / len(files) * 40
            print(f"[{pct:5.1f}%] {completed}/{len(files)}", end="\r", flush=True)
            if success:
                total_success += 1
                status = "✓"
                total_space_freed += space_freed
                if compress:
                    total_original_size += orig_size
            else:
                total_failed += 1
                status = "✗"
            rel_path = filepath.relative_to(root_dir)
            print(f"\n{status} {rel_path}: {message}")
    print(f"\n{'─' * 40}")
    print(f"Total successful: {total_success}")
    print(f"Total failed: {total_failed}")
    if compress and total_original_size > 0:
        print(f"Total original size: {format_bytes(total_original_size)}")
        if total_space_freed > 0:
            print(f"Disk space freed: {format_bytes(total_space_freed)}")


def main():
    parser = argparse.ArgumentParser(
        description="Recursively compress or decompress files using lzma_mt with parallel processing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              python compress_files.py
              python compress_files.py -c --preset 6 --threads 8
              python compress_files.py -d /path/to/files
              python compress_files.py -c /path/to/files --num-workers 8
              python compress_files.py --keep-orig
            Excluded by default:
              - Directories: .git, __pycache__, .venv, venv, node_modules
              - Archives: .zip, .br, .xz, .gz, .bz2, .bz3, .zst, .7z, .lz4, etc.
              - Media: .mp4, .mkv, .mp3, .jpg, .png, .pdf, .exe, etc.
        """),
    )
    parser.add_argument(
        "-c",
        "--compress",
        action="store_true",
        help="Compress files (default if no -d specified)",
    )
    parser.add_argument("-d", "--decompress", action="store_true", help="Decompress .xz files")
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
        "--num-workers",
        type=int,
        default=4,
        help="Number of parallel worker processes (default: 4)",
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
        print("Error: Cannot specify both -c and -d")
        sys.exit(1)
    compress_mode = args.compress or not args.decompress
    root_dir = Path(args.directory).resolve()
    if not root_dir.is_dir():
        print(f"Error: {root_dir} is not a directory")
        sys.exit(1)
    process_files(
        root_dir,
        compress=compress_mode,
        preset=args.preset,
        threads=args.threads,
        num_workers=args.num_workers,
        remove_orig=not args.keep_orig,
    )


if __name__ == "__main__":
    raise SystemExit(main())
