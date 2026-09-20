
import argparse
import brotlicffi
import multiprocessing as mp
from pathlib import Path
from typing import Optional, List, Set
from dataclasses import dataclass
from concurrent.futures import ProcessPoolExecutor, as_completed
import time
import sys


try:
    from rich.console import Console
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
    from rich.panel import Panel
    from rich.text import Text
    from rich import box

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
    compressed_size: int
    success: bool
    error: Optional[str] = None
    duration: float = 0.0
    original_deleted: bool = False


def format_size(size_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def compress_file_streaming(
    input_path: Path,
    output_path: Path,
    quality: int = 11,
    chunk_size: int = 1024 * 1024,  
    keep_original: bool = False,
) -> CompressionResult:
    start_time = time.time()

    try:
        original_size = input_path.stat().st_size

        
        if original_size == 0:
            return CompressionResult(
                file_path=input_path,
                original_size=0,
                compressed_size=0,
                success=False,
                error="Empty file",
                duration=time.time() - start_time,
            )

        
        if original_size < 100:
            return CompressionResult(
                file_path=input_path,
                original_size=original_size,
                compressed_size=original_size,
                success=False,
                error="File too small to compress (< 100 bytes)",
                duration=time.time() - start_time,
            )

        
        compressor = brotlicffi.Compressor(quality=quality)

        compressed_size = 0

        
        with open(input_path, "rb") as f_in:
            with open(output_path, "wb") as f_out:
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
            compressed_size=compressed_size,
            success=True,
            duration=time.time() - start_time,
            original_deleted=original_deleted,
        )

    except Exception as e:
        
        if output_path.exists():
            output_path.unlink()

        return CompressionResult(
            file_path=input_path,
            original_size=input_path.stat().st_size if input_path.exists() else 0,
            compressed_size=0,
            success=False,
            error=str(e),
            duration=time.time() - start_time,
        )


def should_compress_file(file_path: Path, exclude_extensions: Set[str], exclude_patterns: List[str]) -> bool:
    
    if file_path.is_symlink():
        return False

    
    if not file_path.is_file():
        return False

    
    if file_path.suffix.lower() in exclude_extensions:
        return False

    
    if file_path.suffix == ".br":
        return False

    
    if exclude_patterns:
        path_str = str(file_path)
        if any(pattern in path_str for pattern in exclude_patterns):
            return False

    return True


def find_files_to_compress(
    directory: Path,
    exclude_extensions: Set[str] = None,
    exclude_patterns: List[str] = None,
    extensions_filter: List[str] = None,
) -> List[Path]:
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
                    files.append(file_path)
    else:
        
        for file_path in directory.rglob("*"):
            if should_compress_file(file_path, exclude_extensions, exclude_patterns):
                files.append(file_path)

    return sorted(set(files))  


def get_file_type_stats(files: List[Path]) -> dict:
    type_stats = {}
    for file_path in files:
        ext = file_path.suffix.lower() or "[no extension]"
        type_stats[ext] = type_stats.get(ext, 0) + 1
    return dict(sorted(type_stats.items(), key=lambda x: x[1], reverse=True))


def print_results_rich(results: List[CompressionResult], directory: Path):
    console = Console()

    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    
    total_original = sum(r.original_size for r in successful)
    total_compressed = sum(r.compressed_size for r in successful)
    space_saved = total_original - total_compressed
    total_duration = sum(r.duration for r in results)
    deleted_count = sum(1 for r in successful if r.original_deleted)
    avg_ratio = (
        sum((1 - r.compressed_size / r.original_size) * 100 for r in successful) / len(successful) if successful else 0
    )

    
    table = Table(
        title=f"📦 Brotli Compression Results", box=box.ROUNDED, title_style="bold cyan", header_style="bold white"
    )

    table.add_column("File", style="cyan", no_wrap=False)
    table.add_column("Original", justify="right", style="yellow")
    table.add_column("Compressed", justify="right", style="green")
    table.add_column("Ratio", justify="right", style="magenta")
    table.add_column("Time", justify="right", style="dim")
    table.add_column("Status", justify="center")

    
    for result in sorted(successful, key=lambda x: x.original_size, reverse=True)[:20]:
        ratio = (1 - result.compressed_size / result.original_size) * 100 if result.original_size > 0 else 0
        status = "🗑️ ✅" if result.original_deleted else "✅"

        
        try:
            file_display = str(result.file_path.relative_to(directory))
        except ValueError:
            file_display = str(result.file_path)

        table.add_row(
            file_display,
            format_size(result.original_size),
            format_size(result.compressed_size),
            f"{ratio:.1f}%",
            f"{result.duration:.2f}s",
            status,
        )

    if len(successful) > 20:
        table.add_row(f"... and {len(successful) - 20} more files", "", "", "", "", "")

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
    summary_text.append("📊 Summary\n\n", style="bold cyan")
    summary_text.append(f"📁 Directory: ", style="dim")
    summary_text.append(f"{directory}\n", style="bold white")
    summary_text.append(f"Total files processed: ", style="dim")
    summary_text.append(f"{len(results)}\n", style="bold white")
    summary_text.append(f"✅ Successful: ", style="dim")
    summary_text.append(f"{len(successful)}\n", style="bold green")
    summary_text.append(f"❌ Failed: ", style="dim")
    summary_text.append(f"{len(failed)}\n", style="bold red")
    summary_text.append(f"🗑️  Originals deleted: ", style="dim")
    summary_text.append(f"{deleted_count}\n", style="bold yellow")
    summary_text.append(f"\n💾 Total original size: ", style="dim")
    summary_text.append(f"{format_size(total_original)}\n", style="bold yellow")
    summary_text.append(f"📦 Total compressed size: ", style="dim")
    summary_text.append(f"{format_size(total_compressed)}\n", style="bold green")
    summary_text.append(f"📈 Average compression: ", style="dim")
    summary_text.append(f"{avg_ratio:.1f}%\n", style="bold magenta")
    summary_text.append(f"🎉 Disk space freed: ", style="dim")
    summary_text.append(f"{format_size(space_saved)} ", style="bold cyan")
    if total_original > 0:
        summary_text.append(f"({(space_saved / total_original * 100):.1f}%)\n", style="bold cyan")
    summary_text.append(f"⏱️  Total time: ", style="dim")
    summary_text.append(f"{total_duration:.2f}s ", style="bold white")
    if results:
        summary_text.append(f"(avg {total_duration / len(results):.2f}s per file)", style="dim")

    console.print(Panel(summary_text, border_style="cyan"))


def print_results_basic(results: List[CompressionResult], directory: Path):
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    total_original = sum(r.original_size for r in successful)
    total_compressed = sum(r.compressed_size for r in successful)
    space_saved = total_original - total_compressed
    total_duration = sum(r.duration for r in results)
    deleted_count = sum(1 for r in successful if r.original_deleted)
    avg_ratio = (
        sum((1 - r.compressed_size / r.original_size) * 100 for r in successful) / len(successful) if successful else 0
    )

    print("\n" + "=" * 80)
    print(f"📦 Brotli Compression Results")
    print(f"📁 Directory: {directory}")
    print("=" * 80)

    print(f"\n{'File':<40} {'Original':>12} {'Compressed':>12} {'Ratio':>8} {'Time':>8}")
    print("-" * 80)

    for result in sorted(successful, key=lambda x: x.original_size, reverse=True)[:20]:
        ratio = (1 - result.compressed_size / result.original_size) * 100 if result.original_size > 0 else 0
        file_name = result.file_path.name[:37] + "..." if len(result.file_path.name) > 40 else result.file_path.name
        print(
            f"{file_name:<40} {format_size(result.original_size):>12} {format_size(result.compressed_size):>12} {ratio:>7.1f}% {result.duration:>7.2f}s"
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
    print("📊 Summary")
    print("=" * 80)
    print(f"Total files processed: {len(results)}")
    print(f"✅ Successful: {len(successful)}")
    print(f"❌ Failed: {len(failed)}")
    print(f"🗑️  Originals deleted: {deleted_count}")
    print(f"\n💾 Total original size: {format_size(total_original)}")
    print(f"📦 Total compressed size: {format_size(total_compressed)}")
    print(f"📈 Average compression: {avg_ratio:.1f}%")
    print(
        f"🎉 Disk space freed: {format_size(space_saved)} ({(space_saved / total_original * 100) if total_original > 0 else 0:.1f}%)"
    )
    print(
        f"⏱️  Total time: {total_duration:.2f}s (avg {total_duration / len(results):.2f}s per file)" if results else ""
    )
    print("=" * 80 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="📦 Recursively compress all files using Brotli with parallel processing (deletes originals by default)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Compress all files in current directory
  %(prog)s /path/to/directory       # Compress all files in specific directory
  %(prog)s -e txt log csv          # Compress only specific extensions
  %(prog)s -q 11 -w 8              # Custom quality and workers
  %(prog)s --keep-originals        # Keep original files
  %(prog)s --dry-run               # Preview without compressing
  %(prog)s --exclude node_modules .git  # Exclude specific directories
        """,
    )

    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        type=str,
        help="Root directory to compress files recursively (default: current directory)",
    )

    parser.add_argument(
        "-e",
        "--extensions",
        nargs="+",
        help="Compress only specific file extensions (e.g., txt log csv). If not specified, compresses ALL files.",
    )

    parser.add_argument(
        "-q",
        "--quality",
        type=int,
        default=11,
        choices=range(0, 12),
        help="Brotli compression quality (0-11, default: 11)",
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
        help="Keep original files after compression (default: delete originals)",
    )

    parser.add_argument(
        "--exclude",
        nargs="+",
        default=[],
        help="Directory/file patterns to exclude from compression (e.g., node_modules .git)",
    )

    parser.add_argument("--no-parallel", action="store_true", help="Disable parallel processing")

    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be compressed without actually compressing"
    )

    parser.add_argument(
        "--no-skip-compressed",
        action="store_true",
        help="Do not skip already compressed files (dangerous, may double-compress)",
    )

    args = parser.parse_args()

    
    if args.no_skip_compressed:
        exclude_extensions = {".br"}  
        print("⚠️  WARNING: Not skipping already compressed files!")
    else:
        exclude_extensions = EXCLUDED_EXTENSIONS

    directory = Path(args.directory).resolve()
    if not directory.exists():
        print(f"❌ Error: Directory '{directory}' does not exist")
        sys.exit(1)

    if not directory.is_dir():
        print(f"❌ Error: '{directory}' is not a directory")
        sys.exit(1)

    
    print(f"🔍 Scanning directory: {directory}")

    if args.extensions:
        print(f"📁 Mode: Only specified extensions ({', '.join(args.extensions)})")
    else:
        print(f"📁 Mode: ALL files (excluding already compressed formats and symlinks)")

    if args.exclude:
        print(f"🚫 Excluding patterns: {', '.join(args.exclude)}")

    files = find_files_to_compress(
        directory,
        exclude_extensions=exclude_extensions,
        exclude_patterns=args.exclude,
        extensions_filter=args.extensions,
    )

    if not files:
        print(f"❌ No files found to compress")
        sys.exit(0)

    print(f"📁 Found {len(files)} file(s) to compress")

    
    type_stats = get_file_type_stats(files)
    print(f"📊 File types found:")
    for ext, count in list(type_stats.items())[:10]:
        print(f"  • {ext}: {count} file(s)")
    if len(type_stats) > 10:
        print(f"  • ... and {len(type_stats) - 10} more types")

    
    total_size = sum(f.stat().st_size for f in files)
    print(f"💾 Total size: {format_size(total_size)}")

    if args.dry_run:
        print(f"\n🔍 DRY RUN - Would compress {len(files)} files ({format_size(total_size)})")
        print("No files were modified.")
        return

    if not args.keep_originals:
        print("⚠️  Originals will be DELETED after compression (use --keep-originals to preserve)")

    print(f"🎯 Quality: {args.quality}/11")

    
    workers = 1 if args.no_parallel else min(args.workers, len(files))
    print(f"👷 Workers: {workers}")
    print()

    results = []

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
            task = progress.add_task(f"🔄 Compressing files", total=len(files))

            if workers > 1:
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
                        file_path, output_path, args.quality, 1024 * 1024, args.keep_originals
                    )
                    results.append(result)
                    progress.advance(task)
    else:
        
        print(f"🔄 Compressing files...")

        if workers > 1:
            with ProcessPoolExecutor(max_workers=workers) as executor:
                futures = {}
                for file_path in files:
                    output_path = file_path.with_suffix(file_path.suffix + ".br")
                    future = executor.submit(
                        compress_file_streaming, file_path, output_path, args.quality, 1024 * 1024, args.keep_originals
                    )
                    futures[future] = file_path

                for i, future in enumerate(as_completed(futures), 1):
                    result = future.result()
                    results.append(result)
                    status = "🗑️ ✅" if result.success and result.original_deleted else "✅" if result.success else "❌"
                    print(f"  [{i}/{len(files)}] {result.file_path.name} - {status}")
        else:
            for i, file_path in enumerate(files, 1):
                output_path = file_path.with_suffix(file_path.suffix + ".br")
                result = compress_file_streaming(file_path, output_path, args.quality, 1024 * 1024, args.keep_originals)
                results.append(result)
                status = "🗑️ ✅" if result.success and result.original_deleted else "✅" if result.success else "❌"
                print(f"  [{i}/{len(files)}] {file_path.name} - {status}")

    
    if RICH_AVAILABLE:
        print_results_rich(results, directory)
    else:
        print_results_basic(results, directory)


if __name__ == "__main__":
    main()
