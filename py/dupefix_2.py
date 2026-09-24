import shutil
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterable
from multiprocessing import Pool
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import xxhash
from loguru import logger

POOL_SIZE = 8
HASH_CHUNK_SIZE = 8192
DEFAULT_ROOT = "."
FileHashResult = tuple[Path, str | None]


def get_file_hash(filepath):
    try:
        if not filepath.exists():
            return filepath, None
        hasher = xxhash.xxh64()
        with filepath.open("rb") as f:
            while True:
                chunk = f.read(HASH_CHUNK_SIZE)
                if not chunk:
                    break
                hasher.update(chunk)
        return filepath, hasher.hexdigest()
    except (OSError, PermissionError):
        return filepath, None


def _find_candidates(root):
    size_map = defaultdict(list)
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            try:
                size_map[path.stat().st_size].append(path)
            except OSError:
                continue
    candidates = []
    for paths in size_map.values():
        if len(paths) > 1:
            candidates.extend(paths)
    return candidates


def _hash_files(files):
    hash_map = defaultdict(list)
    if not files:
        return hash_map
    with Pool(processes=POOL_SIZE) as pool:
        for result in pool.imap_unordered(get_file_hash, files):
            filepath, file_hash = result
            if file_hash:
                hash_map[file_hash].append(filepath)
    return hash_map


def _delete_file(path):
    try:
        if not path.exists():
            return None
        file_size = path.stat().st_size
        if shutil.which("gio"):
            subprocess.run(["gio", "trash", str(path)], check=True)
        else:
            path.unlink()
        return file_size
    except OSError as exc:
        logger.error("Error deleting {}: {}", path, exc)
        return None


def remove_duplicates(root_dir, dry_run=True):
    root = Path(root_dir)
    logger.info("Scanning directory tree...")
    files_to_hash = _find_candidates(root)
    logger.info("Hashing {} potential duplicate files...", len(files_to_hash))
    hash_map = _hash_files(files_to_hash)
    total_freed = 0
    duplicates_found = 0
    for paths in hash_map.values():
        if len(paths) <= 1:
            continue
        duplicates_found += len(paths) - 1
        paths.sort(key=lambda p: (p.stat().st_mtime, str(p)))
        to_delete = paths[1:]
        for p in to_delete:
            try:
                if not p.exists():
                    continue
                file_size = p.stat().st_size
                if dry_run:
                    logger.info("Would delete: {} ({} bytes)", p, file_size)
                    total_freed += file_size
                else:
                    freed = _delete_file(p)
                    if freed is not None:
                        total_freed += freed
                        logger.info("Deleted: {}", p)
            except OSError as exc:
                logger.error("Error deleting {}: {}", p, exc)
    logger.info("Cleanup complete.")
    logger.info("Duplicate files found: {}", duplicates_found)
    if not dry_run:
        logger.info("Total disk space freed: {:.2f} MB", total_freed / (1024 * 1024))
    else:
        logger.info("Potential space to free: {:.2f} MB", total_freed / (1024 * 1024))
        logger.info("Run with dry_run=False to actually delete files.")


def main(argv=None):
    args = list(argv) if argv is not None else sys.argv[1:]
    target_dir = args[0] if args else DEFAULT_ROOT
    logger.info("DRY RUN - No files will be deleted")
    remove_duplicates(target_dir, dry_run=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
