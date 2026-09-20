from __future__ import annotations

import argparse
import multiprocessing as mp
import shutil
import sys
import tarfile
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import brotlicffi


try:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
    from rich.table import Table
    from rich.text import Text

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("💡 Tip: Install 'rich' for prettier output: pip install rich")
EXCLUDED_EXTENSIONS = {
    ".br",
    ".xz",
    ".zst",
    ".zstd",
    ".7z",
    ".gz",
    ".bz2",
    ".zip",
    ".rar",
    ".tar",
    ".tgz",
    ".tbz2",
    ".txz",
    ".tlz",
    ".lz",
    ".lz4",
    ".lzma",
    ".lzo",
    ".sz",
    ".snappy",
    ".zlib",
    ".deflate",
    ".flac",
    ".mp3",
    ".aac",
    ".ogg",
    ".wma",
    ".opus",
    ".m4a",
    ".wavpack",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".avif",
    ".heic",
    ".heif",
    ".mp4",
    ".avi",
    ".mkv",
    ".mov",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
    ".odt",
    ".ods",
    ".odp",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".wasm",
    ".whl",
    ".egg",
    ".deb",
    ".rpm",
    ".apk",
    ".ipa",
    ".pyc",
    ".pyo",
    ".class",
    ".o",
    ".obj",
    ".lib",
    ".a",
    ".iso",
    ".img",
    ".dmg",
    ".vdi",
    ".vmdk",
    ".qcow2",
}


@dataclass
class CompressionResult:
    file_path: Path
    original_size: int
    processed_size: int
    success: bool
    error: str | None = None
    duration: float = 0.0
    original_deleted: bool = False
    operation: str = "compress"
    was_tarred: bool = False


def format_size(size_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def tar_directory(directory: Path, output_path: Path, delete_original: bool = False) -> tuple[int, bool]:
    try:
        sum(f.stat().st_size for f in directory.rglob("*") if f.is_file())
        with tarfile.open(output_path, "w") as tar:
            tar.add(directory, arcname=directory.name)
        tar_size = output_path.stat().st_size
        if delete_original and output_path.exists():
            shutil.rmtree(directory)
        return (tar_size, True)
    except Exception as e:
        if output_path.exists():
            output_path.unlink()
        raise e


def compress_file_streaming(
    input_path: Path,
    output_path: Path,
    quality: int = 11,
    chunk_size: int = 1024 * 1024,
    keep_original: bool = False,
    was_tarred: bool = False,
) -> CompressionResult:
    start_time = time.time()
    try:
        original_size = input_path.stat().st_size
        if original_size == 0:
            return CompressionResult(
                file_path=input_path,
                original_size=0,
                processed_size=0,
                success=False,
                error="Empty file",
                duration=time.time() - start_time,
                operation="compress",
                was_tarred=was_tarred,
            )
        compressor = brotlicffi.Compressor(quality=quality)
        compressed_size = 0
        with open(input_path, "rb") as f_in, open(output_path, "wb") as f_out:
            while True:
                chunk = f_in.read(chunk_size)
                if not chunk:
                    break
                compressed_chunk = compressor.compress(chunk)
                f_out.write(compressed_chunk)
                compressed_size += len(compressed_chunk)
            remaining = compressor.flush()
            if remaining:
                f_out.write(remaining)
                compressed_size += len(remaining)
        original_deleted = False
        if not keep_original and output_path.exists():
            input_path.unlink()
            original_deleted = True
        return CompressionResult(
            file_path=input_path,
            original_size=original_size,
            processed_size=compressed_size,
            success=True,
            duration=time.time() - start_time,
            original_deleted=original_deleted,
            operation="compress",
            was_tarred=was_tarred,
        )
    except Exception as e:
        if output_path.exists():
            output_path.unlink()
        return CompressionResult(
            file_path=input_path,
            original_size=input_path.stat().st_size if input_path.exists() else 0,
            processed_size=0,
            success=False,
            error=str(e),
            duration=time.time() - start_time,
            operation="compress",
            was_tarred=was_tarred,
        )


def decompress_file_streaming(
    input_path: Path, output_path: Path, chunk_size: int = 1024 * 1024, keep_original: bool = False
) -> CompressionResult:
    start_time = time.time()
    try:
        original_size = input_path.stat().st_size
        if original_size == 0:
            return CompressionResult(
                file_path=input_path,
                original_size=0,
                processed_size=0,
                success=False,
                error="Empty file",
                duration=time.time() - start_time,
                operation="decompress",
            )
        decompressor = brotlicffi.Decompressor()
        decompressed_size = 0
        with open(input_path, "rb") as f_in, open(output_path, "wb") as f_out:
            while True:
                chunk = f_in.read(chunk_size)
                if not chunk:
                    break
                try:
                    decompressed_chunk = decompressor.decompress(chunk)
                    f_out.write(decompressed_chunk)
                    decompressed_size += len(decompressed_chunk)
                except Exception:
                    if decompressed_size > 0:
                        try:
                            remaining = decompressor.flush()
                            if remaining:
                                f_out.write(remaining)
                                decompressed_size += len(remaining)
                        except:
                            pass
                        break
                    else:
                        raise
        original_deleted = False
        if not keep_original and output_path.exists():
            input_path.unlink()
            original_deleted = True
        return CompressionResult(
            file_path=input_path,
            original_size=original_size,
            processed_size=decompressed_size,
            success=True,
            duration=time.time() - start_time,
            original_deleted=original_deleted,
            operation="decompress",
        )
    except Exception as e:
        if output_path.exists():
            output_path.unlink()
        return CompressionResult(
            file_path=input_path,
            original_size=input_path.stat().st_size if input_path.exists() else 0,
            processed_size=0,
            success=False,
            error=str(e),
            duration=time.time() - start_time,
            operation="decompress",
        )


def untar_file(tar_path: Path, extract_dir: Path, delete_tar: bool = False) -> bool:
    try:
        with tarfile.open(tar_path, "r") as tar:
            tar.extractall(extract_dir)
        if delete_tar:
            tar_path.unlink()
        return True
    except Exception as e:
        print(f"Error extracting tar {tar_path}: {e}")
        return False


def process_subdirs_with_tar(
    directory: Path,
    quality: int = 11,
    workers: int = 4,
    keep_original: bool = False,
    exclude_patterns: list[str] | None = None,
) -> list[CompressionResult]:
    if exclude_patterns is None:
        exclude_patterns = []
    results = []
    subdirs = [d for d in directory.iterdir() if d.is_dir() and (not d.is_symlink())]
    subdirs = [d for d in subdirs if not any(pattern in str(d) for pattern in exclude_patterns)]
    excluded_dirs = {".git", ".svn", ".hg", "__pycache__", "node_modules", ".venv", "venv", ".env"}
    subdirs = [d for d in subdirs if d.name not in excluded_dirs]
    if not subdirs:
        print("📁 No subdirectories found to tar")
        return results
    print(f"📁 Found {len(subdirs)} subdirectories to tar first")
    tar_files = []
    tar_errors = []
    print("🗜️  Step 1: Creating tar archives of subdirectories...")
    with tempfile.TemporaryDirectory() as temp_dir:
        Path(temp_dir)
        for i, subdir in enumerate(subdirs, 1):
            try:
                tar_name = f"{subdir.name}.tar"
                tar_path = subdir.parent / tar_name
                if tar_path.exists():
                    print(f"  ⚠️  [{i}/{len(subdirs)}] {tar_name} already exists, skipping tar creation")
                    tar_files.append(tar_path)
                    continue
                print(f"  📦 [{i}/{len(subdirs)}] Tarring {subdir.name}...")
                dir_size = sum(f.stat().st_size for f in subdir.rglob("*") if f.is_file())
                tar_size, success = tar_directory(subdir, tar_path, delete_original=not keep_original)
                if success:
                    tar_files.append(tar_path)
                    if not keep_original:
                        print(f"    ✅ Tarred {format_size(dir_size)} → {format_size(tar_size)} (directory deleted)")
                    else:
                        print(f"    ✅ Tarred {format_size(dir_size)} → {format_size(tar_size)} (directory kept)")
                else:
                    tar_errors.append((subdir, "Failed to create tar"))
            except Exception as e:
                print(f"  ❌ [{i}/{len(subdirs)}] Error tarring {subdir.name}: {e}")
                tar_errors.append((subdir, str(e)))
        if tar_files:
            print(f"\n🗜️  Step 2: Compressing {len(tar_files)} tar files with Brotli (quality: {quality})...")
            if workers > 1 and len(tar_files) > 1:
                with ProcessPoolExecutor(max_workers=workers) as executor:
                    futures = {}
                    for tar_path in tar_files:
                        output_path = tar_path.with_suffix(".tar.br")
                        future = executor.submit(
                            compress_file_streaming,
                            tar_path,
                            output_path,
                            quality,
                            1024 * 1024,
                            not keep_original,
                            was_tarred=True,
                        )
                        futures[future] = tar_path
                    for i, future in enumerate(as_completed(futures), 1):
                        result = future.result()
                        results.append(result)
                        if result.success:
                            print(f"  ✅ [{i}/{len(tar_files)}] {result.file_path.name} → {result.file_path.name}.br")
                            print(
                                f"     {format_size(result.original_size)} → {format_size(result.processed_size)} ({(1 - result.processed_size / result.original_size) * 100:.1f}% compression)"
                            )
                        else:
                            print(f"  ❌ [{i}/{len(tar_files)}] {result.file_path.name}: {result.error}")
            else:
                for i, tar_path in enumerate(tar_files, 1):
                    output_path = tar_path.with_suffix(".tar.br")
                    result = compress_file_streaming(
                        tar_path,
                        output_path,
                        quality,
                        1024 * 1024,
                        not keep_original,
                        was_tarred=True,
                    )
                    results.append(result)
                    if result.success:
                        print(f"  ✅ [{i}/{len(tar_files)}] {tar_path.name} → {tar_path.name}.br")
                        print(
                            f"     {format_size(result.original_size)} → {format_size(result.processed_size)} ({(1 - result.processed_size / result.original_size) * 100:.1f}% compression)"
                        )
                    else:
                        print(f"  ❌ [{i}/{len(tar_files)}] {tar_path.name}: {result.error}")
        if tar_errors:
            print(f"\n❌ Failed to tar {len(tar_errors)} directories:")
            for subdir, error in tar_errors:
                print(f"  • {subdir.name}: {error}")
    return results


def should_compress_file(file_path: Path, exclude_extensions: set[str], exclude_patterns: list[str]) -> bool:
    if file_path.is_symlink():
        return False
    if not file_path.is_file():
        return False
    if file_path.suffix.lower() in exclude_extensions:
        return False
    if file_path.suffix == ".br":
        return False
    if file_path.suffix == ".tar":
        return False
    if exclude_patterns:
        path_str = str(file_path)
        if any(pattern in path_str for pattern in exclude_patterns):
            return False
    return True


def find_files_to_compress(
    directory: Path,
    exclude_extensions: set[str] | None = None,
    exclude_patterns: list[str] | None = None,
    extensions_filter: list[str] | None = None,
    skip_subdirs: bool = False,
) -> list[Path]:
    if exclude_extensions is None:
        exclude_extensions = EXCLUDED_EXTENSIONS
    if exclude_patterns is None:
        exclude_patterns = []
    files = []
    if extensions_filter:
        for ext in extensions_filter:
            ext = ext if ext.startswith(".") else f".{ext}"
            pattern = f"*{ext}"
            for file_path in directory.rglob(pattern):
                if should_compress_file(file_path, exclude_extensions, exclude_patterns):
                    if skip_subdirs and file_path.parent != directory:
                        continue
                    files.append(file_path)
    else:
        for file_path in directory.rglob("*"):
            if should_compress_file(file_path, exclude_extensions, exclude_patterns):
                if skip_subdirs and file_path.parent != directory:
                    continue
                files.append(file_path)
    return sorted(set(files))


def find_files_to_decompress(directory: Path, exclude_patterns: list[str] | None = None) -> list[Path]:
    if exclude_patterns is None:
        exclude_patterns = []
    files = []
    for file_path in directory.rglob("*.br"):
        if file_path.is_symlink():
            continue
        if not file_path.is_file():
            continue
        if exclude_patterns:
            path_str = str(file_path)
            if any(pattern in path_str for pattern in exclude_patterns):
                continue
        files.append(file_path)
    return sorted(set(files))


def get_file_type_stats(files: list[Path]) -> dict:
    type_stats = {}
    for file_path in files:
        ext = file_path.suffix.lower() or "[no extension]"
        type_stats[ext] = type_stats.get(ext, 0) + 1
    return dict(sorted(type_stats.items(), key=lambda x: x[1], reverse=True))


def print_results_rich(results: list[CompressionResult], directory: Path, operation: str):
    console = Console()
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]
    total_original = sum(r.original_size for r in successful)
    total_processed = sum(r.processed_size for r in successful)
    total_duration = sum(r.duration for r in results)
    deleted_count = sum(1 for r in successful if r.original_deleted)
    tarred_count = sum(1 for r in successful if r.was_tarred)
    if operation == "compress":
        space_saved = total_original - total_processed
        avg_ratio = (
            sum((1 - r.processed_size / r.original_size) * 100 for r in successful) / len(successful)
            if successful
            else 0
        )
        operation_emoji = "📦"
        operation_name = "Compression"
        size_label = "Compressed"
    else:
        space_saved = total_processed - total_original
        avg_ratio = (
            sum((r.processed_size / r.original_size - 1) * 100 for r in successful) / len(successful)
            if successful
            else 0
        )
        operation_emoji = "📂"
        operation_name = "Decompression"
        size_label = "Decompressed"
    table = Table(
        title=f"{operation_emoji} Brotli {operation_name} Results",
        box=box.ROUNDED,
        title_style="bold cyan",
        header_style="bold white",
    )
    table.add_column("File", style="cyan", no_wrap=False)
    table.add_column("Original", justify="right", style="yellow")
    table.add_column(size_label, justify="right", style="green")
    table.add_column("Ratio", justify="right", style="magenta")
    table.add_column("Time", justify="right", style="dim")
    table.add_column("Type", justify="center")
    table.add_column("Status", justify="center")
    for result in sorted(successful, key=lambda x: x.original_size, reverse=True)[:20]:
        if operation == "compress":
            ratio = (1 - result.processed_size / result.original_size) * 100 if result.original_size > 0 else 0
        else:
            ratio = (result.processed_size / result.original_size - 1) * 100 if result.original_size > 0 else 0
        status = "🗑️ ✅" if result.original_deleted else "✅"
        file_type = "📦 tar" if result.was_tarred else "📄 file"
        try:
            file_display = str(result.file_path.relative_to(directory))
        except ValueError:
            file_display = str(result.file_path)
        table.add_row(
            file_display,
            format_size(result.original_size),
            format_size(result.processed_size),
            f"{ratio:.1f}%",
            f"{result.duration:.2f}s",
            file_type,
            status,
        )
    if len(successful) > 20:
        table.add_row(f"... and {len(successful) - 20} more files", "", "", "", "", "", "")
    console.print(table)
    if failed:
        fail_table = Table(title="❌ Failed Files", box=box.ROUNDED, title_style="bold red")
        fail_table.add_column("File", style="red")
        fail_table.add_column("Error", style="dim")
        for result in failed[:10]:
            try:
                file_display = str(result.file_path.relative_to(directory))
            except ValueError:
                file_display = str(result.file_path)
            fail_table.add_row(file_display, result.error or "Unknown error")
        if len(failed) > 10:
            fail_table.add_row(f"... and {len(failed) - 10} more failures", "")
        console.print(fail_table)
    summary_text = Text()
    summary_text.append(f"📊 {operation_name} Summary\n\n", style="bold cyan")
    summary_text.append("📁 Directory: ", style="dim")
    summary_text.append(f"{directory}\n", style="bold white")
    summary_text.append("Total files processed: ", style="dim")
    summary_text.append(f"{len(results)}\n", style="bold white")
    summary_text.append("✅ Successful: ", style="dim")
    summary_text.append(f"{len(successful)}\n", style="bold green")
    summary_text.append("❌ Failed: ", style="dim")
    summary_text.append(f"{len(failed)}\n", style="bold red")
    if tarred_count > 0:
        summary_text.append("📦 From tarred directories: ", style="dim")
        summary_text.append(f"{tarred_count}\n", style="bold yellow")
    summary_text.append("🗑️  Originals deleted: ", style="dim")
    summary_text.append(f"{deleted_count}\n", style="bold yellow")
    summary_text.append("\n💾 Total original size: ", style="dim")
    summary_text.append(f"{format_size(total_original)}\n", style="bold yellow")
    summary_text.append(
        f"{('📦' if operation == 'compress' else '📂')} Total {size_label.lower()} size: ",
        style="dim",
    )
    summary_text.append(f"{format_size(total_processed)}\n", style="bold green")
    if operation == "compress":
        summary_text.append("📈 Average compression: ", style="dim")
        summary_text.append(f"{avg_ratio:.1f}%\n", style="bold magenta")
        summary_text.append("🎉 Disk space freed: ", style="dim")
        summary_text.append(f"{format_size(space_saved)} ", style="bold cyan")
    else:
        summary_text.append("📈 Average expansion: ", style="dim")
        summary_text.append(f"{avg_ratio:.1f}%\n", style="bold magenta")
        summary_text.append("💾 Disk space used: ", style="dim")
        summary_text.append(f"{format_size(space_saved)} ", style="bold cyan")
    if total_original > 0 and operation == "compress":
        summary_text.append(f"({space_saved / total_original * 100:.1f}%)\n", style="bold cyan")
    summary_text.append("⏱️  Total time: ", style="dim")
    summary_text.append(f"{total_duration:.2f}s ", style="bold white")
    if results:
        summary_text.append(f"(avg {total_duration / len(results):.2f}s per file)", style="dim")
    console.print(Panel(summary_text, border_style="cyan"))


def print_results_basic(results: list[CompressionResult], directory: Path, operation: str):
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]
    total_original = sum(r.original_size for r in successful)
    total_processed = sum(r.processed_size for r in successful)
    total_duration = sum(r.duration for r in results)
    deleted_count = sum(1 for r in successful if r.original_deleted)
    tarred_count = sum(1 for r in successful if r.was_tarred)
    if operation == "compress":
        space_saved = total_original - total_processed
        avg_ratio = (
            sum((1 - r.processed_size / r.original_size) * 100 for r in successful) / len(successful)
            if successful
            else 0
        )
        operation_name = "Compression"
        size_label = "Compressed"
    else:
        space_saved = total_processed - total_original
        avg_ratio = (
            sum((r.processed_size / r.original_size - 1) * 100 for r in successful) / len(successful)
            if successful
            else 0
        )
        operation_name = "Decompression"
        size_label = "Decompressed"
    print("\n" + "=" * 80)
    print(f"📦 Brotli {operation_name} Results")
    print(f"📁 Directory: {directory}")
    print("=" * 80)
    print(f"\n{'File':<40} {'Original':>12} {size_label:>12} {'Ratio':>8} {'Time':>8}")
    print("-" * 80)
    for result in sorted(successful, key=lambda x: x.original_size, reverse=True)[:20]:
        if operation == "compress":
            ratio = (1 - result.processed_size / result.original_size) * 100 if result.original_size > 0 else 0
        else:
            ratio = (result.processed_size / result.original_size - 1) * 100 if result.original_size > 0 else 0
        file_name = result.file_path.name[:37] + "..." if len(result.file_path.name) > 40 else result.file_path.name
        type_indicator = "[tar]" if result.was_tarred else ""
        print(
            f"{file_name:<40} {format_size(result.original_size):>12} {format_size(result.processed_size):>12} {ratio:>7.1f}% {result.duration:>7.2f}s {type_indicator}"
        )
    if len(successful) > 20:
        print(f"... and {len(successful) - 20} more files")
    if failed:
        print(f"\n❌ Failed files ({len(failed)}):")
        for result in failed[:10]:
            print(f"  • {result.file_path.name}: {result.error}")
        if len(failed) > 10:
            print(f"  ... and {len(failed) - 10} more failures")
    print("\n" + "=" * 80)
    print(f"📊 {operation_name} Summary")
    print("=" * 80)
    print(f"Total files processed: {len(results)}")
    print(f"✅ Successful: {len(successful)}")
    print(f"❌ Failed: {len(failed)}")
    if tarred_count > 0:
        print(f"📦 From tarred directories: {tarred_count}")
    print(f"🗑️  Originals deleted: {deleted_count}")
    print(f"\n💾 Total original size: {format_size(total_original)}")
    print(
        f"{('📦' if operation == 'compress' else '📂')} Total {size_label.lower()} size: {format_size(total_processed)}"
    )
    if operation == "compress":
        print(f"📈 Average compression: {avg_ratio:.1f}%")
        print(
            f"🎉 Disk space freed: {format_size(space_saved)} ({(space_saved / total_original * 100 if total_original > 0 else 0):.1f}%)"
        )
    else:
        print(f"📈 Average expansion: {avg_ratio:.1f}%")
        print(f"💾 Disk space used: {format_size(space_saved)}")
    print(
        f"⏱️  Total time: {total_duration:.2f}s (avg {total_duration / len(results):.2f}s per file)" if results else ""
    )
    print("=" * 80 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="📦 Recursively compress/decompress files using Brotli with parallel processing (deletes originals by default)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\nExamples:\n  %(prog)s                          # Compress all files in current directory\n  %(prog)s -c                       # Compress all files (explicit)\n  %(prog)s -d                       # Decompress all .br files\n  %(prog)s -c -t                    # Tar subdirectories first, then compress\n  %(prog)s -c -t /path/to/dir       # Tar subdirs in specific directory\n  %(prog)s -c -e txt log csv        # Compress only specific extensions\n  %(prog)s -c -q 11 -w 8            # Custom quality and workers\n  %(prog)s -c --keep-originals      # Keep original files when compressing\n  %(prog)s -d --keep-originals      # Keep compressed files when decompressing\n  %(prog)s -c --dry-run             # Preview compression without modifying\n  %(prog)s --exclude node_modules   # Exclude specific directories\n        ",
    )
    operation_group = parser.add_mutually_exclusive_group()
    operation_group.add_argument("-c", "--compress", action="store_true", default=True, help="Compress files (default)")
    operation_group.add_argument("-d", "--decompress", action="store_true", help="Decompress .br files")
    parser.add_argument(
        "-t",
        "--tar-subdirs-first",
        action="store_true",
        help="Tar subdirectories first, then apply Brotli compression on the .tar files (only valid with -c/--compress)",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        type=str,
        help="Root directory to process files recursively (default: current directory)",
    )
    parser.add_argument(
        "-e",
        "--extensions",
        nargs="+",
        help="Compress only specific file extensions (e.g., txt log csv). Only valid with -c/--compress.",
    )
    parser.add_argument(
        "-q",
        "--quality",
        type=int,
        default=11,
        choices=range(12),
        help="Brotli compression quality (0-11, default: 11). Only valid with -c/--compress.",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=mp.cpu_count(),
        help=f"Number of parallel workers (default: {mp.cpu_count()})",
    )
    parser.add_argument(
        "--keep-originals",
        action="store_true",
        help="Keep original files after processing (default: delete originals)",
    )
    parser.add_argument(
        "--exclude",
        nargs="+",
        default=[],
        help="Directory/file patterns to exclude from processing (e.g., node_modules .git)",
    )
    parser.add_argument("--no-parallel", action="store_true", help="Disable parallel processing")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be processed without actually modifying files",
    )
    parser.add_argument(
        "--no-skip-compressed",
        action="store_true",
        help="Do not skip already compressed files (dangerous, may double-compress). Only valid with -c/--compress.",
    )
    args = parser.parse_args()
    operation = "decompress" if args.decompress else "compress"
    if args.tar_subdirs_first and operation == "decompress":
        print("❌ Error: -t/--tar-subdirs-first is only valid with -c/--compress")
        sys.exit(1)
    if operation == "decompress" and (args.extensions or args.no_skip_compressed):
        print("⚠️  Warning: -e/--extensions and --no-skip-compressed are ignored in decompression mode")
    if operation == "decompress" and args.quality != 11:
        print("⚠️  Warning: -q/--quality is ignored in decompression mode")
    if operation == "compress":
        if args.no_skip_compressed:
            exclude_extensions = {".br"}
            print("⚠️  WARNING: Not skipping already compressed files!")
        else:
            exclude_extensions = EXCLUDED_EXTENSIONS
    else:
        exclude_extensions = set()
    directory = Path(args.directory).resolve()
    if not directory.exists():
        print(f"❌ Error: Directory '{directory}' does not exist")
        sys.exit(1)
    if not directory.is_dir():
        print(f"❌ Error: '{directory}' is not a directory")
        sys.exit(1)
    operation_name = "compression" if operation == "compress" else "decompression"
    print(f"🔍 Scanning directory for {operation_name}: {directory}")
    if operation == "compress":
        if args.tar_subdirs_first:
            print("📁 Mode: Tar subdirectories first, then Brotli compression")
            tar_results = process_subdirs_with_tar(
                directory,
                quality=args.quality,
                workers=1 if args.no_parallel else args.workers,
                keep_original=args.keep_originals,
                exclude_patterns=args.exclude,
            )
            print("\n📁 Processing individual files in root directory...")
            files = find_files_to_compress(
                directory,
                exclude_extensions=exclude_extensions,
                exclude_patterns=args.exclude,
                extensions_filter=args.extensions,
                skip_subdirs=True,
            )
            if files:
                print(f"📁 Found {len(files)} individual file(s) in root directory")
                for file_path in files:
                    print(f"  • {file_path.relative_to(directory)}")
            else:
                print("📁 No individual files in root directory")
            all_results = tar_results
        else:
            if args.extensions:
                print(f"📁 Mode: Only specified extensions ({', '.join(args.extensions)})")
            else:
                print("📁 Mode: ALL files (excluding already compressed formats and symlinks)")
            if args.exclude:
                print(f"🚫 Excluding patterns: {', '.join(args.exclude)}")
            files = find_files_to_compress(
                directory,
                exclude_extensions=exclude_extensions,
                exclude_patterns=args.exclude,
                extensions_filter=args.extensions,
                skip_subdirs=False,
            )
            all_results = []
        if not args.tar_subdirs_first and (not files):
            print("❌ No files found to compress")
            sys.exit(0)
        if not args.tar_subdirs_first:
            print(f"📁 Found {len(files)} file(s) to compress")
            type_stats = get_file_type_stats(files)
            if type_stats:
                print("📊 File types found:")
                for ext, count in list(type_stats.items())[:10]:
                    print(f"  • {ext}: {count} file(s)")
                if len(type_stats) > 10:
                    print(f"  • ... and {len(type_stats) - 10} more types")
            total_size = sum(f.stat().st_size for f in files)
            print(f"💾 Total size: {format_size(total_size)}")
    else:
        print("📁 Mode: Decompressing .br files")
        if args.exclude:
            print(f"🚫 Excluding patterns: {', '.join(args.exclude)}")
        files = find_files_to_decompress(directory, exclude_patterns=args.exclude)
        if not files:
            print("❌ No .br files found to decompress")
            sys.exit(0)
        print(f"📁 Found {len(files)} .br file(s) to decompress")
        total_size = sum(f.stat().st_size for f in files)
        print(f"💾 Total compressed size: {format_size(total_size)}")
    if args.dry_run:
        if args.tar_subdirs_first:
            print("\n🔍 DRY RUN - Would tar subdirectories and compress them with Brotli")
        else:
            print(f"\n🔍 DRY RUN - Would {operation} {len(files)} files ({format_size(total_size)})")
        print("No files were modified.")
        return
    if not args.keep_originals:
        if operation == "compress":
            if args.tar_subdirs_first:
                print("⚠️  Subdirectories will be tarred and originals DELETED (use --keep-originals to preserve)")
            else:
                print("⚠️  Originals will be DELETED after compression (use --keep-originals to preserve)")
        else:
            print("⚠️  Compressed .br files will be DELETED after decompression (use --keep-originals to preserve)")
    if operation == "compress":
        print(f"🎯 Quality: {args.quality}/11")
    workers = 1 if args.no_parallel else min(args.workers, len(files) if not args.tar_subdirs_first else args.workers)
    if not args.tar_subdirs_first:
        print(f"👷 Workers: {workers}")
    print()
    results = []
    if args.tar_subdirs_first:
        results = all_results
        if files:
            print("🔄 Compressing individual files...")
            if RICH_AVAILABLE:
                console = Console()
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                    TimeElapsedColumn(),
                    console=console,
                ) as progress:
                    task = progress.add_task("🔄 Compressing individual files", total=len(files))
                    if workers > 1 and len(files) > 1:
                        with ProcessPoolExecutor(max_workers=workers) as executor:
                            futures = {}
                            for file_path in files:
                                output_path = file_path.with_suffix(file_path.suffix + ".br")
                                future = executor.submit(
                                    compress_file_streaming,
                                    file_path,
                                    output_path,
                                    args.quality,
                                    1024 * 1024,
                                    args.keep_originals,
                                )
                                futures[future] = file_path
                            for future in as_completed(futures):
                                result = future.result()
                                results.append(result)
                                progress.advance(task)
                    else:
                        for file_path in files:
                            output_path = file_path.with_suffix(file_path.suffix + ".br")
                            result = compress_file_streaming(
                                file_path,
                                output_path,
                                args.quality,
                                1024 * 1024,
                                args.keep_originals,
                            )
                            results.append(result)
                            progress.advance(task)
            else:
                for i, file_path in enumerate(files, 1):
                    output_path = file_path.with_suffix(file_path.suffix + ".br")
                    result = compress_file_streaming(
                        file_path, output_path, args.quality, 1024 * 1024, args.keep_originals
                    )
                    results.append(result)
                    status = "🗑️ ✅" if result.success and result.original_deleted else "✅" if result.success else "❌"
                    print(f"  [{i}/{len(files)}] {file_path.name} - {status}")
    elif not args.tar_subdirs_first:
        if RICH_AVAILABLE:
            console = Console()
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                task = progress.add_task(f"🔄 {operation_name.capitalize()} files", total=len(files))
                if workers > 1 and len(files) > 1:
                    with ProcessPoolExecutor(max_workers=workers) as executor:
                        futures = {}
                        for file_path in files:
                            if operation == "compress":
                                output_path = file_path.with_suffix(file_path.suffix + ".br")
                                future = executor.submit(
                                    compress_file_streaming,
                                    file_path,
                                    output_path,
                                    args.quality,
                                    1024 * 1024,
                                    args.keep_originals,
                                )
                            else:
                                output_path = file_path.with_suffix("")
                                future = executor.submit(
                                    decompress_file_streaming,
                                    file_path,
                                    output_path,
                                    1024 * 1024,
                                    args.keep_originals,
                                )
                            futures[future] = file_path
                        for future in as_completed(futures):
                            result = future.result()
                            results.append(result)
                            progress.advance(task)
                else:
                    for file_path in files:
                        if operation == "compress":
                            output_path = file_path.with_suffix(file_path.suffix + ".br")
                            result = compress_file_streaming(
                                file_path,
                                output_path,
                                args.quality,
                                1024 * 1024,
                                args.keep_originals,
                            )
                        else:
                            output_path = file_path.with_suffix("")
                            result = decompress_file_streaming(file_path, output_path, 1024 * 1024, args.keep_originals)
                        results.append(result)
                        progress.advance(task)
        else:
            print(f"🔄 {operation_name.capitalize()} files...")
            if workers > 1 and len(files) > 1:
                with ProcessPoolExecutor(max_workers=workers) as executor:
                    futures = {}
                    for file_path in files:
                        if operation == "compress":
                            output_path = file_path.with_suffix(file_path.suffix + ".br")
                            future = executor.submit(
                                compress_file_streaming,
                                file_path,
                                output_path,
                                args.quality,
                                1024 * 1024,
                                args.keep_originals,
                            )
                        else:
                            output_path = file_path.with_suffix("")
                            future = executor.submit(
                                decompress_file_streaming,
                                file_path,
                                output_path,
                                1024 * 1024,
                                args.keep_originals,
                            )
                        futures[future] = file_path
                    for i, future in enumerate(as_completed(futures), 1):
                        result = future.result()
                        results.append(result)
                        status = (
                            "🗑️ ✅" if result.success and result.original_deleted else "✅" if result.success else "❌"
                        )
                        print(f"  [{i}/{len(files)}] {result.file_path.name} - {status}")
            else:
                for i, file_path in enumerate(files, 1):
                    if operation == "compress":
                        output_path = file_path.with_suffix(file_path.suffix + ".br")
                        result = compress_file_streaming(
                            file_path, output_path, args.quality, 1024 * 1024, args.keep_originals
                        )
                    else:
                        output_path = file_path.with_suffix("")
                        result = decompress_file_streaming(file_path, output_path, 1024 * 1024, args.keep_originals)
                    results.append(result)
                    status = "🗑️ ✅" if result.success and result.original_deleted else "✅" if result.success else "❌"
                    print(f"  [{i}/{len(files)}] {file_path.name} - {status}")
    if results:
        if RICH_AVAILABLE:
            print_results_rich(results, directory, operation)
        else:
            print_results_basic(results, directory, operation)


if __name__ == "__main__":
    main()
