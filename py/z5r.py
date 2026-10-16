from __future__ import annotations

import argparse
import multiprocessing as mp
import shutil
import tarfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import zstandard as zstd
from dh import fsz, gsz

DEFAULT_SKIP_DIRS: Final[set[str]] = {
    "zstandard",
    "0",
    "compressed",
    "faprint",
    "packaging",
    "joblib",
    "loguru",
    "setuptools",
    "pip",
    "wheel",
    ".git",
    "dist",
    "build",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
}
try:
    from rich.console import Console
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    RICH_AVAILABLE: Final[bool] = True
except ImportError:
    RICH_AVAILABLE: Final[bool] = False


@dataclass(slots=True)
class FolderResult:
    name: str
    original_size: int = 0
    compressed_size: int = 0
    success: bool = False
    error: str | None = None
    duration: float = 0.0

    @property
    def saved_bytes(self) -> int:
        return max(0, self.original_size - self.compressed_size)


def compress_folder_task(folder_path: Path, output_dir: Path, level: int = 3, threads: int = 0) -> FolderResult:
    start_time = time.perf_counter()
    folder_name = folder_path.name
    zst_path = output_dir / f"{folder_name}.tar.zst"
    temp_tar = output_dir / f".tmp_{folder_name}.tar"
    try:
        orig_size = gsz(folder_path)
        with tarfile.open(temp_tar, "w") as tar:
            tar.add(folder_path, arcname=folder_name)
        cctx = zstd.ZstdCompressor(level=level, threads=threads)
        with (
            temp_tar.open("rb") as f_in,
            zst_path.open("wb") as f_out,
            cctx.stream_writer(f_out) as compressor,
        ):
            shutil.copyfileobj(f_in, compressor)
        comp_size = zst_path.stat().st_size
        temp_tar.unlink()
        shutil.rmtree(folder_path)
        return FolderResult(
            name=folder_name,
            original_size=orig_size,
            compressed_size=comp_size,
            success=True,
            duration=time.perf_counter() - start_time,
        )
    except Exception as e:
        if temp_tar.exists():
            temp_tar.unlink()
        if zst_path.exists():
            zst_path.unlink()
        return FolderResult(name=folder_name, success=False, error=str(e))


def decompress_folder_task(zst_path: Path, output_dir: Path) -> FolderResult:
    start_time = time.perf_counter()
    folder_name = zst_path.name.removesuffix(".tar.zst")
    temp_tar = output_dir / f".tmp_{folder_name}.tar"
    try:
        comp_size = zst_path.stat().st_size
        dctx = zstd.ZstdDecompressor()
        with (
            zst_path.open("rb") as f_in,
            temp_tar.open("wb") as f_out,
            dctx.stream_reader(f_in) as decompressor,
        ):
            shutil.copyfileobj(decompressor, f_out)
        with tarfile.open(temp_tar, "r") as tar:
            tar.extractall(output_dir, filter="data")
        temp_tar.unlink()
        zst_path.unlink()
        extracted_size = gsz(output_dir / folder_name)
        return FolderResult(
            name=folder_name,
            original_size=extracted_size,
            compressed_size=comp_size,
            success=True,
            duration=time.perf_counter() - start_time,
        )
    except Exception as e:
        if temp_tar.exists():
            temp_tar.unlink()
        return FolderResult(name=folder_name, success=False, error=str(e))


def main():
    parser = argparse.ArgumentParser(description="Optimized Folder Zstd Archiver")
    parser.add_argument("-c", "--compress", action="store_true", help="Compress folders")
    parser.add_argument("-d", "--decompress", action="store_true", help="Decompress archives")
    parser.add_argument("-p", "--path", type=Path, default=Path("."), help="Root directory")
    parser.add_argument("-l", "--level", type=int, default=3, help="Compression level (1-22)")
    parser.add_argument("-m", "--min-size", type=float, default=5.0, help="Min folder size in MB")
    parser.add_argument("-w", "--workers", type=int, default=mp.cpu_count(), help="Parallel workers")
    args = parser.parse_args()
    root = args.path.resolve()
    if args.decompress:
        targets = list(root.glob("*.tar.zst"))
        mode_name = "Decompressing"
    else:
        targets = [d for d in root.iterdir() if d.is_dir() and d.name not in DEFAULT_SKIP_DIRS]
        valid_targets = []
        for d in targets:
            size_mb = gsz(d)
            if size_mb >= args.min_size:
                valid_targets.append(d)
        targets = valid_targets
        mode_name = "Compressing"
    if not targets:
        print("No targets found to process.")
        return
    print(f"🚀 {mode_name} {len(targets)} items in {root}...")
    results: list[FolderResult] = []
    if RICH_AVAILABLE:
        console = Console()
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(f"{mode_name}...", total=len(targets))
            with ProcessPoolExecutor(max_workers=args.workers) as executor:
                if args.decompress:
                    futures = [executor.submit(decompress_folder_task, t, root) for t in targets]
                else:
                    futures = [executor.submit(compress_folder_task, t, root, args.level) for t in targets]
                for f in as_completed(futures):
                    res = f.result()
                    results.append(res)
                    progress.advance(task)
                    if not res.success:
                        console.print(f"[red]Error on {res.name}: {res.error}[/red]")
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            if args.decompress:
                futures = [executor.submit(decompress_folder_task, t, root) for t in targets]
            else:
                futures = [executor.submit(compress_folder_task, t, root, args.level) for t in targets]
            for i, f in enumerate(as_completed(futures), 1):
                res = f.result()
                results.append(res)
                print(f"[{i}/{len(targets)}] {res.name} - {('OK' if res.success else 'FAIL')}")
    successes = [r for r in results if r.success]
    print(f"\n{'=' * 40}")
    print(f"SUMMARY ({mode_name})")
    print(f"{'=' * 40}")
    print(f"Total: {len(results)}")
    print(f"Success: {len(successes)}")
    print(f"Failed: {len(results) - len(successes)}")
    if successes:
        total_orig = sum(r.original_size for r in successes)
        total_comp = sum(r.compressed_size for r in successes)
        if args.decompress:
            print(f"Extracted size: {fsz(total_orig)}")
        else:
            print(f"Space saved: {fsz(total_orig - total_comp)}")
    print(f"{'=' * 40}")


if __name__ == "__main__":
    main()
