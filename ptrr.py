import io
import multiprocessing
import os
import shutil
import sys
import tarfile
from collections.abc import Iterable
from multiprocessing.pool import Pool
from pathlib import Path
from typing import List, Tuple
from loguru import logger

WORKERS = 8

ARCHIVE_SUFFIX = ".tar.xz"
def find_files(root):
    if not root.exists():
        raise FileNotFoundError(f"Root directory does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Root path is not a directory: {root}")
    files = []
    for dirpath, _dirnames, filenames in os.walk(root):
        base = Path(dirpath)
        for name in filenames:
            candidate = base / name
            
            if candidate.is_file() and not candidate.is_symlink():
                files.append(candidate)
            elif candidate.is_symlink() and not candidate.exists():
                logger.warning(f"Skipping broken symlink: {candidate}")
    return files
def _read_file(path):
    return path, path.read_bytes()
def compress_files(files):
    file_list = list(files)
    if not file_list:
        return []
    print(f"Reading {len(file_list)} file(s) with {WORKERS} workers")
    with Pool(processes=WORKERS) as pool:
        results = pool.map(_read_file, file_list)
    return results
def build_archive(
    archive_path,
    root,
    payload,
):
    print(f"Writing archive: {archive_path}")
    top_level = root.name  
    with tarfile.open(
        name=str(archive_path),
        mode="w:xz",
        preset=6,
        format=tarfile.PAX_FORMAT,
    ) as tar:
        for path, content in payload:
            try:
                rel = path.relative_to(root)
            except ValueError:
                
                rel = Path(path.name)
            
            
            arcname = Path(top_level) / rel
            info = tarfile.TarInfo(name=str(arcname))
            info.size = len(content)
            info.mtime = path.stat().st_mtime
            tar.addfile(info, io.BytesIO(content))
    logger.success(f"Archive created: {archive_path}")
def remove_directory(root):
    print(f"Removing original directory: {root}")
    shutil.rmtree(root)
    logger.success(f"Removed: {root}")
def archive_current_directory():
    cwd = Path.cwd().resolve()
    parent = cwd.parent
    top_level = cwd.name
    archive_path = parent / f"{top_level}{ARCHIVE_SUFFIX}"
    print(f"Current directory: {cwd}")
    print(f"Target archive:    {archive_path}")
    if archive_path.exists():
        raise RuntimeError(f"Archive already exists: {archive_path}")
    files = find_files(cwd)
    if not files:
        raise RuntimeError(f"No files found to archive in: {cwd}")
    payload = compress_files(files)
    build_archive(archive_path, cwd, payload)
    
    if not archive_path.is_file() or archive_path.stat().st_size == 0:
        raise RuntimeError(f"Archive verification failed: {archive_path}")
    with tarfile.open(archive_path, mode="r:xz") as tar:
        members = tar.getnames()
    
    expected_prefix = f"{top_level}/"
    unexpected = [m for m in members if not m.startswith(expected_prefix)]
    if unexpected:
        raise RuntimeError(
            f"Archive contains members outside '{expected_prefix}': {unexpected[:5]}"
        )
    if len(members) != len(files):
        raise RuntimeError(
            f"Archive member count mismatch: expected {len(files)}, "
            f"found {len(members)}"
        )
    os.chdir(parent)
    remove_directory(cwd)
    return archive_path
def main():
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<level>{message}</level>"
        ),
    )
    try:
        archive = archive_current_directory()
    except Exception as exc:  
        logger.exception(f"Archiving failed: {exc}")
        return 1
    logger.success(f"Done. Archive: {archive}")
    return 0
if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
