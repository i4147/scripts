from __future__ import annotations

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import zstandard as zstd

GREEN = "\x1b[92m"
YELLOW = "\x1b[93m"
BLUE = "\x1b[94m"
RED = "\x1b[91m"
RESET = "\x1b[0m"


class ProgressDisplay:
    def __init__(self):
        self.lock = threading.Lock()
        self.total_files = 0
        self.processed_files = 0
        self.total_size = 0
        self.compressed_size = 0
        self.start_time = time.time()

    def update(self, file_path, original_size, compressed_size, status="compressed"):
        with self.lock:
            self.processed_files += 1
            self.total_size += original_size
            self.compressed_size += compressed_size
            elapsed = time.time() - self.start_time
            if self.total_files > 0:
                percent = self.processed_files / self.total_files * 40
            else:
                percent = 0
            if self.total_size > 0:
                ratio = self.compressed_size / self.total_size
                savings = (1 - ratio) * 40
            else:
                ratio = 1
                savings = 0
            if elapsed > 0:
                speed = self.total_size / (1024 * 1024) / elapsed
            else:
                speed = 0
            bar_length = 30
            filled = int(bar_length * percent / 100)
            bar = "=" * filled + ">" + "." * (bar_length - filled - 1)
            status_color = GREEN if status == "compressed" else YELLOW
            filename = Path(file_path).name
            if len(filename) > 30:
                filename = filename[:27] + "..."
            print(
                f"\r{status_color}{status.upper():10}{RESET} [{bar}] {percent:5.1f}% {self.processed_files}/{
                    self.total_files
                } files ({savings:5.1f}% saved, {speed:5.1f} MB/s) - {filename:<30}",
                end="",
                flush=True,
            )

    def set_total_files(self, count):
        self.total_files = count

    def finish(self):
        elapsed = time.time() - self.start_time
        print()
        print(f"\n{GREEN}✓ Compression complete!{RESET}")
        print(f"  Files processed: {self.processed_files}/{self.total_files}")
        if self.total_size > 0:
            orig_mb = self.total_size / (1024 * 1024)
            comp_mb = self.compressed_size / (1024 * 1024)
            savings = (1 - self.compressed_size / self.total_size) * 40
            print(f"  Original size: {orig_mb:.2f} MB")
            print(f"  Compressed size: {comp_mb:.2f} MB")
            print(f"  Savings: {savings:.1f}%")
            print(f"  Time: {elapsed:.1f} seconds")
            print(f"  Average speed: {self.total_size / (1024 * 1024) / elapsed:.1f} MB/s")


def should_compress_file(file_path, threshold):
    compressed_extensions = {
        ".zst",
        ".gz",
        ".bz2",
        ".xz",
        ".zip",
        ".rar",
        ".7z",
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".mp4",
        ".avi",
        ".mkv",
        ".mp3",
        ".flac",
        ".pdf",
    }
    if file_path.suffix.lower() in compressed_extensions:
        return False
    try:
        size = file_path.stat().st_size
        return size > threshold
    except OSError:
        return False


def compress_file(file_path, progress, level=3):
    original_size = file_path.stat().st_size
    compressed_path = file_path.with_suffix(file_path.suffix + ".zst")
    temp_path = file_path.with_suffix(file_path.suffix + ".zst.tmp")
    try:
        cctx = zstd.ZstdCompressor(level=level, threads=4)
        with open(file_path, "rb") as f_in:
            data = f_in.read()
        compressed_data = cctx.compress(data)
        compressed_size = len(compressed_data)
        if compressed_size < original_size:
            with open(temp_path, "wb") as f_out:
                f_out.write(compressed_data)
            temp_path.rename(compressed_path)
            file_path.unlink()
            progress.update(file_path, original_size, compressed_size, "compressed")
            return True, file_path, compressed_path, compressed_size
        else:
            progress.update(file_path, original_size, original_size, "skipped")
            return False, file_path, None, original_size
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        progress.update(file_path, original_size, original_size, f"error: {str(e)[:20]}")
        return False, file_path, None, original_size


def main():
    if len(sys.argv) != 2:
        print(f"{RED}Usage: python {sys.argv[0]} <threshold_in_bytes>{RESET}")
        print(f"Example: python {sys.argv[0]} 1048576  # Compress files > 1MB")
        print(f"Example: python {sys.argv[0]} 5242880  # Compress files > 5MB")
        sys.exit(1)
    try:
        threshold = int(sys.argv[1])
        if threshold <= 0:
            print(f"{RED}Threshold must be positive{RESET}")
            sys.exit(1)
    except ValueError:
        print(f"{RED}Invalid threshold. Please provide a number in bytes.{RESET}")
        sys.exit(1)
    if threshold >= 1024 * 1024 * 1024:
        threshold_str = f"{threshold / (1024 * 1024 * 1024):.1f} GB"
    elif threshold >= 1024 * 1024:
        threshold_str = f"{threshold / (1024 * 1024):.1f} MB"
    elif threshold >= 1024:
        threshold_str = f"{threshold / 1024:.1f} KB"
    else:
        threshold_str = f"{threshold} bytes"
    print(f"{BLUE}Compressing files larger than {threshold_str}{RESET}")
    print(f"{YELLOW}Scanning current directory...{RESET}")
    current_dir = Path.cwd()
    files_to_compress = []
    for file_path in current_dir.rglob("*"):
        if file_path.is_file() and should_compress_file(file_path, threshold):
            files_to_compress.append(file_path)
    if not files_to_compress:
        print(f"{YELLOW}No files found larger than {threshold_str}{RESET}")
        return
    print(f"{GREEN}Found {len(files_to_compress)} files to compress{RESET}")
    progress = ProgressDisplay()
    progress.set_total_files(len(files_to_compress))
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(compress_file, f, progress): f for f in files_to_compress}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                print(f"\n{RED}Error processing file: {e}{RESET}")
    progress.finish()


if __name__ == "__main__":
    raise SystemExit(main())
