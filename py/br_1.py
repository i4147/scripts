from __future__ import annotations
import argparse
import hashlib
import multiprocessing as mp
import shutil
import sys
import tarfile
import time
from concurrent.futures import Future, ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional, Sequence
import brotlicffi

try:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
    from rich.table import Table
    from rich.text import Text

    RICH_AVAILABLE: bool = True
except ImportError:
    RICH_AVAILABLE = False
    print("💡 Tip: Install 'rich' for prettier output: pip install rich")
DEFAULT_CHUNK_SIZE: int = 1024 * 1024
MIN_CHUNK_SIZE: int = 4096
EXCLUDED_EXTENSIONS: set[str] = {
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
EXCLUDED_DIRS: set[str] = {".git", ".svn", ".hg", "__pycache__", "node_modules", ".venv", "venv", ".env"}


@dataclass
class CompressionResult:
    file_path: Path
    original_size: int
    processed_size: int
    success: bool
    error: Optional[str] = None
    duration: float = 0.0
    original_deleted: bool = False
    operation: str = "compress"
    was_tarred: bool = False
    verified: bool = False


def format_size(size_bytes: float) -> str:
    size: float = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def directory_size(directory: Path) -> int:
    total: int = 0
    for item in directory.rglob("*"):
        if item.is_file() and not item.is_symlink():
            total += item.stat().st_size
    return total


def compressed_output_path(path: Path) -> Path:
    return path.with_name(path.name + ".br")


def decompressed_output_path(path: Path) -> Path:
    if path.name.endswith(".br") and len(path.name) > 3:
        return path.with_name(path.name[:-3])
    return path.with_name(path.name + ".out")


def roots_display(roots: Sequence[Path]) -> str:
    if len(roots) == 1:
        return str(roots[0])
    head: str = ", ".join(str(r) for r in roots[:3])
    tail: str = f" (+{len(roots) - 3} more)" if len(roots) > 3 else ""
    return f"{len(roots)} paths: {head}{tail}"


def relative_display(path: Path, roots: Sequence[Path]) -> str:
    for root in roots:
        try:
            return str(path.relative_to(root))
        except ValueError:
            continue
    return str(path)


def stream_compress(
    input_path: Path, output_path: Path, quality: int, chunk_size: int, flush_each_chunk: bool, hash_input: bool
) -> tuple[int, Optional[str]]:
    compressor = brotlicffi.Compressor(quality=quality)
    hasher = hashlib.sha256() if hash_input else None
    written: int = 0
    with open(input_path, "rb") as f_in, open(output_path, "wb") as f_out:
        while True:
            chunk: bytes = f_in.read(chunk_size)
            if not chunk:
                break
            if hasher is not None:
                hasher.update(chunk)
            payload: bytes = compressor.compress(chunk)
            if flush_each_chunk:
                payload += compressor.flush()
            if payload:
                f_out.write(payload)
                written += len(payload)
        tail: bytes = compressor.finish()
        if tail:
            f_out.write(tail)
            written += len(tail)
    return written, hasher.hexdigest() if hasher is not None else None


def stream_decompress(
    input_path: Path, output_path: Optional[Path], chunk_size: int, allow_truncated: bool, hash_output: bool
) -> tuple[int, Optional[str]]:
    decompressor = brotlicffi.Decompressor()
    hasher = hashlib.sha256() if hash_output else None
    written: int = 0
    f_out = open(output_path, "wb") if output_path is not None else None
    try:
        with open(input_path, "rb") as f_in:
            while True:
                chunk: bytes = f_in.read(chunk_size)
                if not chunk:
                    break
                payload: bytes = decompressor.decompress(chunk)
                if payload:
                    if f_out is not None:
                        f_out.write(payload)
                    if hasher is not None:
                        hasher.update(payload)
                    written += len(payload)
    finally:
        if f_out is not None:
            f_out.close()
    if not decompressor.is_finished() and not allow_truncated:
        msg = "Incomplete Brotli stream (missing end-of-stream marker)"
        raise ValueError(msg)
    return written, hasher.hexdigest() if hasher is not None else None


def tar_directory(directory: Path, output_path: Path, delete_original: bool = False) -> tuple[int, bool]:
    try:
        with tarfile.open(output_path, "w") as tar:
            tar.add(directory, arcname=directory.name)
        tar_size: int = output_path.stat().st_size
        if delete_original and output_path.exists():
            shutil.rmtree(directory)
        return tar_size, True
    except Exception:
        if output_path.exists():
            output_path.unlink()
        raise


def compress_file_streaming(
    input_path: Path,
    output_path: Path,
    quality: int = 11,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    keep_original: bool = False,
    was_tarred: bool = False,
    verify: bool = False,
) -> CompressionResult:
    start_time: float = time.time()
    try:
        original_size: int = input_path.stat().st_size
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
        try:
            compressed_size, source_digest = stream_compress(
                input_path, output_path, quality, chunk_size, False, verify
            )
        except AssertionError:
            if output_path.exists():
                output_path.unlink()
            compressed_size, source_digest = stream_compress(input_path, output_path, quality, chunk_size, True, verify)
        if verify:
            check_size, check_digest = stream_decompress(output_path, None, chunk_size, False, True)
            if check_size != original_size or check_digest != source_digest:
                msg = "Verification failed: round-trip does not match source"
                raise ValueError(msg)
        original_deleted: bool = False
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
            verified=verify,
        )
    except Exception as e:
        if output_path.exists():
            output_path.unlink()
        return CompressionResult(
            file_path=input_path,
            original_size=input_path.stat().st_size if input_path.exists() else 0,
            processed_size=0,
            success=False,
            error=f"{type(e).__name__}: {e}" if str(e) else type(e).__name__,
            duration=time.time() - start_time,
            operation="compress",
            was_tarred=was_tarred,
        )


def decompress_file_streaming(
    input_path: Path,
    output_path: Path,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    keep_original: bool = False,
    allow_truncated: bool = False,
) -> CompressionResult:
    start_time: float = time.time()
    try:
        original_size: int = input_path.stat().st_size
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
        decompressed_size, _ = stream_decompress(input_path, output_path, chunk_size, allow_truncated, False)
        original_deleted: bool = False
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
            error=f"{type(e).__name__}: {e}" if str(e) else type(e).__name__,
            duration=time.time() - start_time,
            operation="decompress",
        )


def untar_file(tar_path: Path, extract_dir: Path, delete_tar: bool = False) -> bool:
    try:
        with tarfile.open(tar_path, "r") as tar:
            try:
                tar.extractall(extract_dir, filter="data")
            except TypeError:
                tar.extractall(extract_dir)
        if delete_tar:
            tar_path.unlink()
        return True
    except Exception as e:
        print(f"  ❌ Error extracting tar {tar_path.name}: {e}")
        return False


def find_subdirs_to_tar(roots: Sequence[Path], exclude_patterns: Optional[list[str]] = None) -> list[Path]:
    patterns: list[str] = exclude_patterns or []
    subdirs: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for d in root.iterdir():
            if d.is_dir() and not d.is_symlink():
                if any(pattern in str(d) for pattern in patterns):
                    continue
                if d.name in EXCLUDED_DIRS:
                    continue
                subdirs.append(d)
    return sorted(set(subdirs))


def report_tar_result(result: CompressionResult, index: int, total: int) -> None:
    if result.success:
        ratio: float = (1 - result.processed_size / result.original_size) * 100 if result.original_size else 0.0
        print(f"  ✅ [{index}/{total}] {result.file_path.name} → {result.file_path.name}.br")
        print(
            f"     {format_size(result.original_size)} → {format_size(result.processed_size)} "
            f"({ratio:.1f}% compression)"
        )
    else:
        print(f"  ❌ [{index}/{total}] {result.file_path.name}: {result.error}")


def process_subdirs_with_tar(
    roots: Sequence[Path],
    quality: int = 11,
    workers: int = 4,
    keep_original: bool = False,
    exclude_patterns: Optional[list[str]] = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    verify: bool = False,
) -> list[CompressionResult]:
    results: list[CompressionResult] = []
    subdirs: list[Path] = find_subdirs_to_tar(roots, exclude_patterns)
    if not subdirs:
        print("📁 No subdirectories found to tar")
        return results
    print(f"📁 Found {len(subdirs)} subdirectories to tar first")
    print("🗜️  Step 1: Creating tar archives of subdirectories...")
    tar_files: list[Path] = []
    tar_errors: list[tuple[Path, str]] = []
    for i, subdir in enumerate(subdirs, 1):
        try:
            tar_path: Path = subdir.parent / f"{subdir.name}.tar"
            if tar_path.exists():
                print(f"  ⚠️  [{i}/{len(subdirs)}] {tar_path.name} already exists, skipping tar creation")
                tar_files.append(tar_path)
                continue
            print(f"  📦 [{i}/{len(subdirs)}] Tarring {subdir.name}...")
            dir_size: int = directory_size(subdir)
            tar_size, success = tar_directory(subdir, tar_path, delete_original=not keep_original)
            if success:
                tar_files.append(tar_path)
                state: str = "directory kept" if keep_original else "directory deleted"
                print(f"    ✅ Tarred {format_size(dir_size)} → {format_size(tar_size)} ({state})")
            else:
                tar_errors.append((subdir, "Failed to create tar"))
        except Exception as e:
            print(f"  ❌ [{i}/{len(subdirs)}] Error tarring {subdir.name}: {e}")
            tar_errors.append((subdir, str(e)))
    jobs: list[tuple[Path, Path]] = []
    for tar_path in tar_files:
        output_path: Path = compressed_output_path(tar_path)
        if output_path.exists():
            print(f"  ⚠️  {output_path.name} already exists, skipping")
            continue
        jobs.append((tar_path, output_path))
    if jobs:
        print(f"\n🗜️  Step 2: Compressing {len(jobs)} tar files with Brotli (quality: {quality})...")
        if workers > 1 and len(jobs) > 1:
            with ProcessPoolExecutor(max_workers=workers) as executor:
                futures: dict[Future, Path] = {}
                for tar_path, output_path in jobs:
                    future = executor.submit(
                        compress_file_streaming,
                        tar_path,
                        output_path,
                        quality=quality,
                        chunk_size=chunk_size,
                        keep_original=False,
                        was_tarred=True,
                        verify=verify,
                    )
                    futures[future] = tar_path
                for i, future in enumerate(as_completed(futures), 1):
                    result: CompressionResult = future.result()
                    results.append(result)
                    report_tar_result(result, i, len(jobs))
        else:
            for i, (tar_path, output_path) in enumerate(jobs, 1):
                result = compress_file_streaming(
                    tar_path,
                    output_path,
                    quality=quality,
                    chunk_size=chunk_size,
                    keep_original=False,
                    was_tarred=True,
                    verify=verify,
                )
                results.append(result)
                report_tar_result(result, i, len(jobs))
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
        path_str: str = str(file_path)
        if any(pattern in path_str for pattern in exclude_patterns):
            return False
    return True


def find_files_to_compress(
    roots: Sequence[Path],
    exclude_extensions: Optional[set[str]] = None,
    exclude_patterns: Optional[list[str]] = None,
    extensions_filter: Optional[Sequence[str]] = None,
    skip_subdirs: bool = False,
) -> list[Path]:
    extensions: set[str] = EXCLUDED_EXTENSIONS if exclude_extensions is None else exclude_extensions
    patterns: list[str] = exclude_patterns or []
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            if should_compress_file(root, extensions, patterns):
                files.append(root)
            continue
        if not root.is_dir():
            continue
        if extensions_filter:
            for raw_ext in extensions_filter:
                ext: str = raw_ext if raw_ext.startswith(".") else f".{raw_ext}"
                for file_path in root.rglob(f"*{ext}"):
                    if should_compress_file(file_path, extensions, patterns):
                        if skip_subdirs and file_path.parent != root:
                            continue
                        files.append(file_path)
        else:
            for file_path in root.rglob("*"):
                if should_compress_file(file_path, extensions, patterns):
                    if skip_subdirs and file_path.parent != root:
                        continue
                    files.append(file_path)
    return sorted(set(files))


def find_files_to_decompress(roots: Sequence[Path], exclude_patterns: Optional[list[str]] = None) -> list[Path]:
    patterns: list[str] = exclude_patterns or []
    files: list[Path] = []
    for root in roots:
        candidates: Iterator[Path]
        if root.is_file():
            candidates = iter([root])
        elif root.is_dir():
            candidates = root.rglob("*.br")
        else:
            continue
        for file_path in candidates:
            if file_path.is_symlink():
                continue
            if not file_path.is_file():
                continue
            if not file_path.name.endswith(".br"):
                continue
            if patterns and any(pattern in str(file_path) for pattern in patterns):
                continue
            files.append(file_path)
    return sorted(set(files))


def get_file_type_stats(files: list[Path]) -> dict[str, int]:
    type_stats: dict[str, int] = {}
    for file_path in files:
        ext: str = file_path.suffix.lower() or "[no extension]"
        type_stats[ext] = type_stats.get(ext, 0) + 1
    return dict(sorted(type_stats.items(), key=lambda x: x[1], reverse=True))


def run_jobs(
    jobs: list[tuple[Path, Path]],
    operation: str,
    quality: int,
    chunk_size: int,
    keep_original: bool,
    workers: int,
    verify: bool,
    allow_truncated: bool,
) -> Iterator[CompressionResult]:
    if workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures: list[Future] = []
            for input_path, output_path in jobs:
                if operation == "compress":
                    futures.append(
                        executor.submit(
                            compress_file_streaming,
                            input_path,
                            output_path,
                            quality=quality,
                            chunk_size=chunk_size,
                            keep_original=keep_original,
                            was_tarred=False,
                            verify=verify,
                        )
                    )
                else:
                    futures.append(
                        executor.submit(
                            decompress_file_streaming,
                            input_path,
                            output_path,
                            chunk_size=chunk_size,
                            keep_original=keep_original,
                            allow_truncated=allow_truncated,
                        )
                    )
            for future in as_completed(futures):
                yield future.result()
    else:
        for input_path, output_path in jobs:
            if operation == "compress":
                yield compress_file_streaming(
                    input_path,
                    output_path,
                    quality=quality,
                    chunk_size=chunk_size,
                    keep_original=keep_original,
                    was_tarred=False,
                    verify=verify,
                )
            else:
                yield decompress_file_streaming(
                    input_path,
                    output_path,
                    chunk_size=chunk_size,
                    keep_original=keep_original,
                    allow_truncated=allow_truncated,
                )


def process_files(
    files: list[Path],
    roots: Sequence[Path],
    operation: str,
    quality: int = 11,
    workers: int = 8,
    keep_original: bool = False,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    verify: bool = False,
    allow_truncated: bool = False,
) -> list[CompressionResult]:
    results: list[CompressionResult] = []
    jobs: list[tuple[Path, Path]] = []
    for file_path in files:
        output_path: Path = (
            compressed_output_path(file_path) if operation == "compress" else decompressed_output_path(file_path)
        )
        if output_path.exists():
            results.append(
                CompressionResult(
                    file_path=file_path,
                    original_size=file_path.stat().st_size if file_path.exists() else 0,
                    processed_size=0,
                    success=False,
                    error=f"Output already exists: {output_path.name}",
                    operation=operation,
                )
            )
            continue
        jobs.append((file_path, output_path))
    if not jobs:
        return results
    label: str = "Compressing" if operation == "compress" else "Decompressing"
    stream: Iterator[CompressionResult] = run_jobs(
        jobs, operation, quality, chunk_size, keep_original, workers, verify, allow_truncated
    )
    if RICH_AVAILABLE:
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
        ) as progress:
            task = progress.add_task(label, total=len(jobs))
            for result in stream:
                results.append(result)
                progress.advance(task)
    else:
        for i, result in enumerate(stream, 1):
            results.append(result)
            status: str = "✅" if result.success else "❌"
            detail: str = (
                f"{format_size(result.original_size)} → {format_size(result.processed_size)}"
                if result.success
                else str(result.error)
            )
            print(f"  {status} [{i}/{len(jobs)}] {relative_display(result.file_path, roots)}: {detail}")
    return results


def extract_decompressed_tars(results: list[CompressionResult], keep_tar: bool) -> tuple[int, int]:
    extracted: int = 0
    failed: int = 0
    for result in results:
        if not result.success:
            continue
        tar_path: Path = decompressed_output_path(result.file_path)
        if tar_path.suffix != ".tar" or not tar_path.exists():
            continue
        if untar_file(tar_path, tar_path.parent, delete_tar=not keep_tar):
            extracted += 1
            print(f"  📂 Extracted {tar_path.name}")
        else:
            failed += 1
    return extracted, failed


def print_results_rich(results: list[CompressionResult], roots: Sequence[Path], operation: str) -> None:
    console = Console()
    successful: list[CompressionResult] = [r for r in results if r.success]
    failed: list[CompressionResult] = [r for r in results if not r.success]
    total_original: int = sum(r.original_size for r in successful)
    total_processed: int = sum(r.processed_size for r in successful)
    total_duration: float = sum(r.duration for r in results)
    deleted_count: int = sum(1 for r in successful if r.original_deleted)
    tarred_count: int = sum(1 for r in successful if r.was_tarred)
    verified_count: int = sum(1 for r in successful if r.verified)
    if operation == "compress":
        space_saved: int = total_original - total_processed
        avg_ratio: float = (
            sum((1 - r.processed_size / r.original_size) * 100 for r in successful) / len(successful)
            if successful
            else 0.0
        )
        operation_emoji: str = "📦"
        operation_name: str = "Compression"
        size_label: str = "Compressed"
    else:
        space_saved = total_processed - total_original
        avg_ratio = (
            sum((r.processed_size / r.original_size - 1) * 100 for r in successful) / len(successful)
            if successful
            else 0.0
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
            ratio: float = (1 - result.processed_size / result.original_size) * 100 if result.original_size > 0 else 0.0
        else:
            ratio = (result.processed_size / result.original_size - 1) * 100 if result.original_size > 0 else 0.0
        status: str = "🗑️ ✅" if result.original_deleted else "✅"
        if result.verified:
            status += "🔐"
        file_type: str = "📦 tar" if result.was_tarred else "📄 file"
        table.add_row(
            relative_display(result.file_path, roots),
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
            fail_table.add_row(relative_display(result.file_path, roots), result.error or "Unknown error")
        if len(failed) > 10:
            fail_table.add_row(f"... and {len(failed) - 10} more failures", "")
        console.print(fail_table)
    summary_text = Text()
    summary_text.append(f"📊 {operation_name} Summary\n\n", style="bold cyan")
    summary_text.append("📁 Target: ", style="dim")
    summary_text.append(f"{roots_display(roots)}\n", style="bold white")
    summary_text.append("Total files processed: ", style="dim")
    summary_text.append(f"{len(results)}\n", style="bold white")
    summary_text.append("✅ Successful: ", style="dim")
    summary_text.append(f"{len(successful)}\n", style="bold green")
    summary_text.append("❌ Failed: ", style="dim")
    summary_text.append(f"{len(failed)}\n", style="bold red")
    if tarred_count > 0:
        summary_text.append("📦 From tarred directories: ", style="dim")
        summary_text.append(f"{tarred_count}\n", style="bold yellow")
    if verified_count > 0:
        summary_text.append("🔐 Round-trip verified: ", style="dim")
        summary_text.append(f"{verified_count}\n", style="bold green")
    summary_text.append("🗑️  Originals deleted: ", style="dim")
    summary_text.append(f"{deleted_count}\n", style="bold yellow")
    summary_text.append("\n💾 Total original size: ", style="dim")
    summary_text.append(f"{format_size(total_original)}\n", style="bold yellow")
    summary_text.append(f"{'📦' if operation == 'compress' else '📂'} Total {size_label.lower()} size: ", style="dim")
    summary_text.append(f"{format_size(total_processed)}\n", style="bold green")
    if operation == "compress":
        summary_text.append("📈 Average compression: ", style="dim")
        summary_text.append(f"{avg_ratio:.1f}%\n", style="bold magenta")
        summary_text.append("🎉 Disk space freed: ", style="dim")
        summary_text.append(f"{format_size(space_saved)} ", style="bold cyan")
        if total_original > 0:
            summary_text.append(f"({space_saved / total_original * 100:.1f}%)\n", style="bold cyan")
        else:
            summary_text.append("\n", style="bold cyan")
    else:
        summary_text.append("📈 Average expansion: ", style="dim")
        summary_text.append(f"{avg_ratio:.1f}%\n", style="bold magenta")
        summary_text.append("💾 Disk space used: ", style="dim")
        summary_text.append(f"{format_size(space_saved)}\n", style="bold cyan")
    summary_text.append("⏱️  Total time: ", style="dim")
    summary_text.append(f"{total_duration:.2f}s ", style="bold white")
    if results:
        summary_text.append(f"(avg {total_duration / len(results):.2f}s per file)", style="dim")
    console.print(Panel(summary_text, border_style="cyan"))


def print_results_basic(results: list[CompressionResult], roots: Sequence[Path], operation: str) -> None:
    successful: list[CompressionResult] = [r for r in results if r.success]
    failed: list[CompressionResult] = [r for r in results if not r.success]
    total_original: int = sum(r.original_size for r in successful)
    total_processed: int = sum(r.processed_size for r in successful)
    total_duration: float = sum(r.duration for r in results)
    deleted_count: int = sum(1 for r in successful if r.original_deleted)
    tarred_count: int = sum(1 for r in successful if r.was_tarred)
    verified_count: int = sum(1 for r in successful if r.verified)
    if operation == "compress":
        space_saved: int = total_original - total_processed
        avg_ratio: float = (
            sum((1 - r.processed_size / r.original_size) * 100 for r in successful) / len(successful)
            if successful
            else 0.0
        )
        operation_name: str = "Compression"
        size_label: str = "Compressed"
    else:
        space_saved = total_processed - total_original
        avg_ratio = (
            sum((r.processed_size / r.original_size - 1) * 100 for r in successful) / len(successful)
            if successful
            else 0.0
        )
        operation_name = "Decompression"
        size_label = "Decompressed"
    print("\n" + "=" * 80)
    print(f"📦 Brotli {operation_name} Results")
    print(f"📁 Target: {roots_display(roots)}")
    print("=" * 80)
    print(f"\n{'File':<40} {'Original':>12} {size_label:>12} {'Ratio':>8} {'Time':>8}")
    print("-" * 80)
    for result in sorted(successful, key=lambda x: x.original_size, reverse=True)[:20]:
        if operation == "compress":
            ratio: float = (1 - result.processed_size / result.original_size) * 100 if result.original_size > 0 else 0.0
        else:
            ratio = (result.processed_size / result.original_size - 1) * 100 if result.original_size > 0 else 0.0
        name: str = result.file_path.name
        file_name: str = name[:37] + "..." if len(name) > 40 else name
        type_indicator: str = "[tar]" if result.was_tarred else ""
        print(
            f"{file_name:<40} {format_size(result.original_size):>12} "
            f"{format_size(result.processed_size):>12} {ratio:>7.1f}% {result.duration:>7.2f}s {type_indicator}"
        )
    if len(successful) > 20:
        print(f"... and {len(successful) - 20} more files")
    if failed:
        print(f"\n❌ Failed files ({len(failed)}):")
        for result in failed[:10]:
            print(f"  • {relative_display(result.file_path, roots)}: {result.error}")
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
    if verified_count > 0:
        print(f"🔐 Round-trip verified: {verified_count}")
    print(f"🗑️  Originals deleted: {deleted_count}")
    print(f"\n💾 Total original size: {format_size(total_original)}")
    print(
        f"{'📦' if operation == 'compress' else '📂'} Total {size_label.lower()} size: {format_size(total_processed)}"
    )
    if operation == "compress":
        pct: float = (space_saved / total_original * 100) if total_original > 0 else 0.0
        print(f"📈 Average compression: {avg_ratio:.1f}%")
        print(f"🎉 Disk space freed: {format_size(space_saved)} ({pct:.1f}%)")
    else:
        print(f"📈 Average expansion: {avg_ratio:.1f}%")
        print(f"💾 Disk space used: {format_size(space_saved)}")
    if results:
        print(f"⏱️  Total time: {total_duration:.2f}s (avg {total_duration / len(results):.2f}s per file)")
    print("=" * 80 + "\n")


def print_dry_run(
    files: list[Path], roots: Sequence[Path], operation: str, subdirs: Optional[list[Path]] = None
) -> None:
    total_size: int = 0
    for file_path in files:
        try:
            total_size += file_path.stat().st_size
        except OSError:
            continue
    label: str = "compressed" if operation == "compress" else "decompressed"
    print("\n" + "=" * 80)
    print(f"🔍 DRY RUN — nothing will be modified ({operation})")
    print(f"📁 Target: {roots_display(roots)}")
    print("=" * 80)
    if subdirs:
        print(
            f"\n📦 Subdirectories to tar first: {len(subdirs)} ({format_size(sum(directory_size(d) for d in subdirs))})"
        )
        for subdir in subdirs[:20]:
            print(f"  • {subdir.name}/  {format_size(directory_size(subdir))}")
        if len(subdirs) > 20:
            print(f"  ... and {len(subdirs) - 20} more directories")
    print(f"\n📄 Files to be {label}: {len(files)} ({format_size(total_size)})")
    if files:
        print("\nBy type:")
        for ext, count in list(get_file_type_stats(files).items())[:15]:
            print(f"  {ext:<20} {count}")
        print("\nLargest files:")
        for file_path in sorted(files, key=lambda p: p.stat().st_size if p.exists() else 0, reverse=True)[:20]:
            size: int = file_path.stat().st_size if file_path.exists() else 0
            print(f"  {relative_display(file_path, roots):<60} {format_size(size):>12}")
        if len(files) > 20:
            print(f"  ... and {len(files) - 20} more files")
    print("=" * 80 + "\n")


def print_header(
    operation: str,
    roots: Sequence[Path],
    quality: int,
    workers: int,
    keep_original: bool,
    tar_mode: bool,
    verify: bool,
) -> None:
    emoji: str = "📦" if operation == "compress" else "📂"
    action: str = "Compressing" if operation == "compress" else "Decompressing"
    details: str = f"workers: {workers} | {'keep originals' if keep_original else 'delete originals'}"
    if operation == "compress":
        details = f"quality: {quality} | " + details
        if tar_mode:
            details += " | tar subdirs first"
        if verify:
            details += " | verify round-trip"
    header: str = f"{emoji} Brotli {action} — {roots_display(roots)}"
    if RICH_AVAILABLE:
        Console().print(Panel(f"[bold cyan]{header}[/bold cyan]\n[dim]{details}[/dim]", border_style="cyan"))
    else:
        print("\n" + "=" * 80)
        print(header)
        print(details)
        print("=" * 80)


def confirm(prompt: str) -> bool:
    if not sys.stdin.isatty():
        print(f"❌ Refusing to delete originals without confirmation: {prompt}")
        print("   Re-run with -y/--yes (non-interactive) or --keep-originals")
        return False
    return input(f"⚠️  {prompt} [y/N] ").strip().lower() in ("y", "yes")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="📦 Recursively compress/decompress files using Brotli with parallel processing (deletes originals by default)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
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
        "paths",
        nargs="*",
        help="One or more files/directories to process (default: current directory)",
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
        default=8,
        help=f"Number of parallel workers (default: {mp.cpu_count()})",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=f"Streaming chunk size in bytes (default: {DEFAULT_CHUNK_SIZE}, minimum: {MIN_CHUNK_SIZE})",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Decompress each result in memory and compare SHA-256 with the source before deleting originals",
    )
    parser.add_argument(
        "--keep-originals", action="store_true", help="Keep original files after processing (default: delete originals)"
    )
    parser.add_argument(
        "--untar",
        action="store_true",
        help="Extract .tar files produced by decompression (only valid with -d/--decompress)",
    )
    parser.add_argument(
        "--allow-truncated",
        action="store_true",
        help="Accept Brotli streams without an end-of-stream marker (only valid with -d/--decompress)",
    )
    parser.add_argument(
        "--exclude",
        nargs="+",
        default=[],
        help="Directory/file patterns to exclude from processing (e.g., node_modules .git).",
    )
    parser.add_argument("--no-parallel", action="store_true", help="Disable parallel processing")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be processed without actually modifying files"
    )
    parser.add_argument(
        "--no-skip-compressed",
        action="store_true",
        help="Do not skip already compressed files (dangerous, may double-compress). Only valid with -c/--compress.",
    )
    parser.add_argument(
        "-y", "--yes", action="store_true", help="Skip the confirmation prompt shown before deleting originals"
    )
    args = parser.parse_args()
    operation: str = "decompress" if args.decompress else "compress"
    if operation == "decompress":
        if args.tar_subdirs_first:
            print("❌ Error: -t/--tar-subdirs-first is only valid with -c/--compress")
            return 1
        if args.extensions:
            print("❌ Error: -e/--extensions is only valid with -c/--compress")
            return 1
        if args.no_skip_compressed:
            print("❌ Error: --no-skip-compressed is only valid with -c/--compress")
            return 1
        if args.verify:
            print("❌ Error: --verify is only valid with -c/--compress")
            return 1
    else:
        if args.untar:
            print("❌ Error: --untar is only valid with -d/--decompress")
            return 1
        if args.allow_truncated:
            print("❌ Error: --allow-truncated is only valid with -d/--decompress")
            return 1
    if args.chunk_size < MIN_CHUNK_SIZE:
        print(f"❌ Error: --chunk-size must be at least {MIN_CHUNK_SIZE} bytes")
        return 1
    raw_paths: list[str] = args.paths if args.paths else ["."]
    roots: list[Path] = [Path(p).expanduser().resolve() for p in raw_paths]
    for root in roots:
        if not root.exists():
            print(f"❌ Error: path does not exist: {root}")
            return 1
        if root == Path(root.anchor) and not args.keep_originals and not args.dry_run:
            print(f"❌ Error: refusing to run destructively on the filesystem root: {root}")
            return 1
    workers: int = 1 if args.no_parallel else max(1, args.workers)
    keep_original: bool = args.keep_originals
    exclude_patterns: list[str] = list(args.exclude)
    exclude_extensions: set[str] = set() if args.no_skip_compressed else set(EXCLUDED_EXTENSIONS)
    chunk_size: int = args.chunk_size
    results: list[CompressionResult] = []
    wall_start: float = time.time()
    try:
        if operation == "compress":
            subdirs: list[Path] = find_subdirs_to_tar(roots, exclude_patterns) if args.tar_subdirs_first else []
            files: list[Path] = find_files_to_compress(
                roots, exclude_extensions, exclude_patterns, args.extensions, skip_subdirs=args.tar_subdirs_first
            )
            if args.dry_run:
                print_dry_run(files, roots, operation, subdirs)
                return 0
            if not files and not subdirs:
                print("✨ Nothing to compress")
                return 0
            print_header(operation, roots, args.quality, workers, keep_original, args.tar_subdirs_first, args.verify)
            if not keep_original and not args.yes:
                targets: str = f"{len(files)} files"
                if subdirs:
                    targets += f" and {len(subdirs)} directories"
                if not confirm(f"Originals will be DELETED in {roots_display(roots)} ({targets}). Continue?"):
                    print("🚫 Aborted")
                    return 130
            if args.tar_subdirs_first:
                results.extend(
                    process_subdirs_with_tar(
                        roots, args.quality, workers, keep_original, exclude_patterns, chunk_size, args.verify
                    )
                )
            if files:
                print(f"\n🗜️  Compressing {len(files)} files with Brotli (quality: {args.quality})...")
                results.extend(
                    process_files(
                        files, roots, operation, args.quality, workers, keep_original, chunk_size, args.verify
                    )
                )
        else:
            files = find_files_to_decompress(roots, exclude_patterns)
            if args.dry_run:
                print_dry_run(files, roots, operation)
                return 0
            if not files:
                print("✨ No .br files found to decompress")
                return 0
            print_header(operation, roots, args.quality, workers, keep_original, False, False)
            if not keep_original and not args.yes:
                if not confirm(
                    f"Compressed originals will be DELETED in {roots_display(roots)} ({len(files)} files). Continue?"
                ):
                    print("🚫 Aborted")
                    return 130
            print(f"\n📂 Decompressing {len(files)} files...")
            results = process_files(
                files,
                roots,
                operation,
                args.quality,
                workers,
                keep_original,
                chunk_size,
                False,
                args.allow_truncated,
            )
            if args.untar:
                print("\n📦 Extracting decompressed tar archives...")
                extracted, extract_failed = extract_decompressed_tars(results, keep_original)
                print(f"  ✅ Extracted: {extracted} | ❌ Failed: {extract_failed}")
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
        return 130
    except Exception as e:
        print(f"\n❌ Fatal error: {type(e).__name__}: {e}")
        return 1
    if not results:
        print("✨ Nothing processed")
        return 0
    if RICH_AVAILABLE:
        print_results_rich(results, roots, operation)
    else:
        print_results_basic(results, roots, operation)
    print(f"⏲️  Wall clock: {time.time() - wall_start:.2f}s")
    successful: int = sum(1 for r in results if r.success)
    return 0 if successful else 1


if __name__ == "__main__":
    mp.freeze_support()
    sys.exit(main())
