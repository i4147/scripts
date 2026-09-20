import mimetypes
from pathlib import Path
from multiprocessing import Pool, cpu_count
from typing import Tuple, List
import logging
from collections import defaultdict
from dh import BIN_EXT

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def is_binary_file(file_path: Path) -> bool:
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(8192)
        if not chunk:
            return None
        if b"\x00" in chunk:
            return True
        non_text_chars = sum((1 for byte in chunk if byte < 32 and byte not in (9, 10, 13)))
        if len(chunk) > 0:
            non_text_ratio = non_text_chars / len(chunk)
            if non_text_ratio > 0.3:
                return True
        try:
            chunk.decode("utf-8")
            return False
        except UnicodeDecodeError:
            for encoding in ["latin-1", "iso-8859-1", "cp1252"]:
                try:
                    chunk.decode(encoding)
                    return False
                except (UnicodeDecodeError, LookupError):
                    continue
            return True
    except (OSError, IOError, PermissionError):
        return None


def check_file(file_path: Path) -> tuple[Path, str, bool, str]:
    try:
        extension = file_path.suffix.lower()
        is_binary = is_binary_file(file_path)
        mime_type, _ = mimetypes.guess_type(str(file_path))
        mime_type = mime_type or "unknown"
        return (file_path, extension, is_binary, mime_type)
    except Exception as e:
        logger.error(f"Error processing {file_path}: {e}")
        return (file_path, file_path.suffix.lower(), None, "error")


def find_files_with_extensions(root_dir: Path, extensions: set) -> list[Path]:
    matching_files = []
    extensions_lower = {ext.lower() for ext in extensions}


"""
Memory-efficient filesystem traversal with progress reporting.
Optimized for large-scale Linux filesystem scans.
"""

import os
from pathlib import Path
from typing import Iterator, Set, Tuple
import logging

logger = logging.getLogger(__name__)


def get_filez(root_dir: str, extensions: set[str], progress_callback=None, batch_size: int = 1000) -> Iterator[Path]:
    extensions_lower = {ext.lower() for ext in extensions}
    file_count = 0
    try:
        for dirpath, dirnames, filenames in os.walk(root_dir):
            if progress_callback and file_count % batch_size == 0:
                progress_callback(dirpath, file_count)
            dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__"}]
            for filename in filenames:
                file_path = Path(dirpath) / filename
                if file_path.is_symlink():
                    continue
                if file_path.suffix.lower() in extensions_lower:
                    file_count += 1
                    yield file_path
                    if progress_callback and file_count % batch_size == 0:
                        progress_callback(dirpath, file_count)
    except PermissionError as e:
        logger.warning(f"Permission denied accessing {root_dir}: {e}")
    except OSError as e:
        logger.error(f"OS error during traversal: {e}")


def get_files(
    root_dir: str,
    extensions: set[str],
    progress_callback=None,
    skip_symlinks: bool = True,
    skip_mount_points: bool = True,
) -> Iterator[Path]:
    extensions_lower = {ext.lower() for ext in extensions}
    visited_inodes = set()
    file_count = 0
    try:
        for dirpath, dirnames, filenames in os.walk(
            root_dir, topdown=True, onerror=lambda e: logger.warning(f"Walk error: {e}")
        ):
            try:
                dir_stat = os.stat(dirpath)
                dir_inode = (dir_stat.st_dev, dir_stat.st_ino)
                if skip_symlinks and dir_inode in visited_inodes:
                    dirnames[:] = []
                    continue
                visited_inodes.add(dir_inode)
                if skip_mount_points and dirpath != root_dir:
                    root_stat = os.stat(root_dir)
                    if dir_stat.st_dev != root_stat.st_dev:
                        dirnames[:] = []
                        continue
            except (OSError, FileNotFoundError):
                dirnames[:] = []
                continue
            if progress_callback and file_count % 1000 == 0:
                progress_callback(dirpath, file_count)
            for filename in filenames:
                try:
                    file_path = Path(dirpath) / filename
                    if file_path.suffix.lower() in extensions_lower:
                        file_count += 1
                        yield file_path
                except (OSError, FileNotFoundError):
                    continue
    except KeyboardInterrupt:
        logger.info("Traversal interrupted by user")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during traversal: {e}")


class ProgressReporter:
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.last_count = 0

    def __call__(self, current_path: str, file_count: int):
        if not self.verbose:
            return
        if file_count - self.last_count >= 1000:
            self.last_count = file_count
            path_display = current_path[:70] + "..." if len(current_path) > 70 else current_path
            print(
                f"\r[Progress] Files found: {file_count:8d} | Current: {path_display}",
                end="",
                flush=True,
            )


class ColorProgressReporter:
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.last_count = 0
        self.colors = {
            "reset": "\x1b[0m",
            "bold": "\x1b[1m",
            "cyan": "\x1b[36m",
            "green": "\x1b[32m",
            "yellow": "\x1b[33m",
        }

    def __call__(self, current_path: str, file_count: int):
        if not self.verbose:
            return
        if file_count - self.last_count >= 1000:
            self.last_count = file_count
            path_display = current_path[:50] + "..." if len(current_path) > 50 else current_path
            msg = f"\r{self.colors['cyan']}[{self.colors['bold']}●{self.colors['reset']}{self.colors['cyan']}]{self.colors['reset']} {self.colors['green']}{file_count:8d}{self.colors['reset']} files | {self.colors['yellow']}{path_display}{self.colors['reset']}"
            print(msg, end="", flush=True)


class SpinnerProgressReporter:
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.last_count = 0
        self.spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.spinner_index = 0

    def __call__(self, current_path: str, file_count: int):
        if not self.verbose:
            return
        if file_count - self.last_count >= 1000:
            self.last_count = file_count
            self.spinner_index = (self.spinner_index + 1) % len(self.spinner)
            path_display = current_path[:50] + "..." if len(current_path) > 50 else current_path
            msg = f"\r{self.spinner[self.spinner_index]} Files: {file_count:8d} | {path_display}"
            print(msg, end="", flush=True)


def validate_extensions(root_dir: str = "/", num_workers: int = None) -> dict:
    if num_workers is None:
        num_workers = max(1, cpu_count() - 1)
    root_path = Path(root_dir)
    if not root_path.exists():
        logger.error(f"Root directory {root_dir} does not exist")
        return {}
    logger.info(f"Starting filesystem traversal from {root_dir}...")
    logger.info(f"Looking for extensions: {sorted(BIN_EXT)}")
    logger.info(f"Using {num_workers} worker processes")
    matching_files = find_files_with_extensions(root_path, BIN_EXT)
    logger.info(f"Found {len(matching_files)} files with target extensions")
    if not matching_files:
        logger.warning("No files found with specified extensions")
        return {
            "total_files": 0,
            "binary_files": 0,
            "text_files": 0,
            "access_errors": 0,
            "mismatches": [],
            "by_extension": {},
        }
    logger.info("Checking file types...")
    with Pool(num_workers) as pool:
        results = pool.map(check_file, matching_files)
    binary_count = 0
    text_count = 0
    error_count = 0
    mismatches = []
    by_extension = defaultdict(lambda: {"binary": 0, "text": 0, "error": 0, "files": []})
    for file_path, ext, is_binary, mime_type in results:
        by_extension[ext]["files"].append({"path": str(file_path), "is_binary": is_binary, "mime_type": mime_type})
        if is_binary is True:
            binary_count += 1
            by_extension[ext]["binary"] += 1
        elif is_binary is False:
            text_count += 1
            by_extension[ext]["text"] += 1
            mismatches.append({"path": str(file_path), "extension": ext, "mime_type": mime_type})
        else:
            error_count += 1
            by_extension[ext]["error"] += 1
    return {
        "total_files": len(matching_files),
        "binary_files": binary_count,
        "text_files": text_count,
        "access_errors": error_count,
        "mismatches": mismatches,
        "by_extension": dict(by_extension),
    }


def print_report(results: dict):
    print("\n" + "=" * 80)
    print("BINARY EXTENSION VALIDATION REPORT")
    print("=" * 80)
    print(f"\nSummary:")
    print(f"  Total files found:    {results['total_files']}")
    print(f"  Actual binary files:  {results['binary_files']}")
    print(f"  Text files:           {results['text_files']}")
    print(f"  Access errors:        {results['access_errors']}")
    if results["mismatches"]:
        print(
            f"\n⚠️  MISMATCHES FOUND: {len(results['mismatches'])} files with binary extension are actually TEXT files"
        )
        print("-" * 80)
        for mismatch in results["mismatches"][:20]:
            print(f"  {mismatch['path']}")
            print(f"    Extension: {mismatch['extension']}")
            print(f"    MIME type: {mismatch['mime_type']}")
        if len(results["mismatches"]) > 20:
            print(f"  ... and {len(results['mismatches']) - 20} more")
    else:
        print(f"\n✓ No mismatches found! All files match their extensions.")
    print(f"\nBreakdown by extension:")
    print("-" * 80)
    for ext, stats in sorted(results["by_extension"].items()):
        print(f"  {ext:12} - Binary: {stats['binary']:6}  Text: {stats['text']:6}  Errors: {stats['error']:6}")
    print("\n" + "=" * 80)


if __name__ == "__main__":
    import sys

    root_dir = sys.argv[1] if len(sys.argv) > 1 else "/"
    results = validate_extensions(root_dir)
    print_report(results)
    sys.exit(1 if results["mismatches"] else 0)
