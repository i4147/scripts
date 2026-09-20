import argparse
import concurrent.futures
import os
from collections import defaultdict
from pathlib import Path
from loguru import logger
from xxhash import xxh64

DEFAULT_BLOCK = 32768
QUICK_READ = 4096


def file_stat_key(p: Path) -> tuple[int, int] | None:
    try:
        st = p.stat()
        return (st.st_ino, st.st_dev)
    except Exception:
        return None


def quick_hash(path: Path, n: int = QUICK_READ) -> str:
    h = xxh64()
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            head = f.read(n)
            h.update(head)
            if size > n * 2:
                f.seek(max(size - n, 0))
                tail = f.read(n)
                h.update(tail)
            else:
                f.seek(0)
                rest = f.read()
                h.update(rest)
    except Exception as e:
        raise IOError(f"quick_hash error {path}: {e}")
    return h.hexdigest()


def full_hash(path: Path, block_size: int = DEFAULT_BLOCK) -> str:
    h = xxh64()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(block_size), b""):
                h.update(chunk)
    except Exception as e:
        raise IOError(f"full_hash error {path}: {e}")
    return h.hexdigest()


def iter_files(root: Path, recursive: bool, follow_symlinks: bool, min_size: int):
    if recursive:
        for p in root.rglob("*"):
            if p.is_file() and (follow_symlinks or not p.is_symlink()):
                try:
                    if p.stat().st_size >= min_size:
                        yield p
                except Exception:
                    continue
    else:
        for p in root.iterdir():
            if p.is_file() and (follow_symlinks or not p.is_symlink()):
                try:
                    if p.stat().st_size >= min_size:
                        yield p
                except Exception:
                    continue


def choose_keep(files, policy="first"):
    if policy == "first":
        return min(files, key=lambda p: str(p))
    if policy == "oldest":
        return min(files, key=lambda p: p.stat().st_mtime)
    if policy == "newest":
        return max(files, key=lambda p: p.stat().st_mtime)
    return min(files, key=lambda p: str(p))


def main() -> None:
    p = argparse.ArgumentParser(description="Find and delete duplicate files by content.")
    p.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Search directories recursively (default: False).",
    )
    p.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Don't delete; just show what would be done.",
    )
    p.add_argument("--follow-symlinks", action="store_true", help="Follow symlinks to files.")
    p.add_argument(
        "--min-size",
        type=int,
        default=1,
        help="Minimum file size (bytes) to consider. Default 1 (skip zero-size).",
    )
    p.add_argument(
        "--keep",
        choices=("first", "oldest", "newest"),
        default="first",
        help="Which file to keep within duplicates.",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Don't prompt for confirmation when deleting.",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=(os.cpu_count() or 4) * 2,
        help="Number of worker threads for hashing.",
    )
    args = p.parse_args()
    root = Path.cwd()
    logger.info(f"Scanning {root} (recursive={args.recursive}) ...")
    size_groups = defaultdict(list)
    total_files = 0
    for f in iter_files(root, args.recursive, args.follow_symlinks, args.min_size):
        total_files += 1
        try:
            size_groups[f.stat().st_size].append(f)
        except Exception:
            continue
    candidates_by_size = {s: lst for s, lst in size_groups.items() if len(lst) > 1}
    if not candidates_by_size:
        logger.info("No potential duplicates found (no groups with equal size).")
        return
    logger.info(
        f"Found {sum(len(v) for v in candidates_by_size.values())} files in {len(candidates_by_size)} size-groups to examine."
    )
    quick_groups = defaultdict(list)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {}
        for files in candidates_by_size.values():
            for fpath in files:
                futures[ex.submit(quick_hash, fpath)] = fpath
        for fut in concurrent.futures.as_completed(futures):
            fpath = futures[fut]
            try:
                h = fut.result()
                key = (fpath.stat().st_size, h)
                quick_groups[key].append(fpath)
            except Exception as e:
                logger.info(f"Skipping {fpath}: {e}")
    need_full = [group for group in quick_groups.values() if len(group) > 1]
    if not need_full:
        logger.info("No duplicates after quick-hash stage.")
        return
    full_groups = defaultdict(list)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {}
        for group in need_full:
            for fpath in group:
                st_key = file_stat_key(fpath)
                futures[ex.submit(full_hash, fpath)] = (fpath, st_key)
        for fut in concurrent.futures.as_completed(futures):
            fpath, st_key = futures[fut]
            try:
                h = fut.result()
                full_groups[h].append((fpath, st_key))
            except Exception as e:
                logger.info(f"Skipping {fpath}: {e}")
    to_delete = []
    for h, entries in full_groups.items():
        inode_map = {}
        for p, stk in entries:
            inode_map.setdefault(stk, []).append(p)
        group_reps = [sorted(ps)[0] for ps in inode_map.values()]
        if len(group_reps) < 2:
            continue
        keep_file = choose_keep(group_reps, policy=args.keep)
        for ps in group_reps:
            if ps == keep_file:
                continue
            to_delete.append(ps)
    if not to_delete:
        logger.info("No duplicates to delete.")
        return
    logger.info(f"Planned deletions: {len(to_delete)} files.")
    for p in to_delete:
        logger.info("  " + str(p))
    if args.dry_run:
        logger.info("Dry-run enabled; no files were deleted.")
        return
    if not args.yes:
        ans = input("Proceed to delete these files? [y/N]: ").strip().lower()
        if ans not in ("y", "yes"):
            logger.info("Aborted by user.")
            return
    removed = 0
    failed = 0
    for p in to_delete:
        try:
            p.unlink()
            logger.info(f"Deleted: {p}")
            removed += 1
        except Exception as e:
            logger.info(f"Failed to delete {p}: {e}")
            failed += 1
    logger.info(f"Done. Removed: {removed}. Failed: {failed}.")


if __name__ == "__main__":
    main()
