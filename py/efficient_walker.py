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
