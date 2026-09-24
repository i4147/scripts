import argparse
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from xxhash import xxh64

SKIP_DIRS = frozenset({"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"})
DEFAULT_BLOCK = 32768
QUICK_READ = 4096
CHUNK_SIZE = 65536


def file_stat_key(p: Path) -> tuple[int, int] | None:
    try:
        st = p.stat()
        return (st.st_ino, st.st_dev)
    except OSError:
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
            elif size > n:
                rest = f.read()
                h.update(rest)
    except (OSError, IOError) as e:
        raise OSError(f"quick_hash error {path}: {e}")
    return h.hexdigest()


def full_hash(path: Path) -> tuple[str, Path]:
    try:
        if not path.stat().st_size:
            return ("", path)
    except OSError:
        return ("", path)
    h = xxh64()
    try:
        with path.open("rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                h.update(chunk)
        return (h.hexdigest(), path)
    except (OSError, IOError):
        return ("", path)


def iter_files(root: Path, recursive: bool, follow_symlinks: bool, min_size: int):
    if recursive:
        iterator = root.rglob("*")
    else:
        iterator = root.iterdir()
    for p in iterator:
        if not p.is_file():
            continue
        if not follow_symlinks and p.is_symlink():
            continue
        try:
            if p.stat().st_size >= min_size:
                yield p
        except OSError:
            continue


def choose_keep(files: list, policy: str = "oldest") -> Path:
    if not files:
        raise ValueError("Empty file list")
    if policy == "first":
        return min(files, key=str)
    elif policy == "oldest":
        return min(files, key=lambda p: p.stat().st_mtime)
    elif policy == "newest":
        return max(files, key=lambda p: p.stat().st_mtime)
    else:
        return min(files, key=str)


def main() -> None:
    cwd = Path.cwd()
    p = argparse.ArgumentParser(description="Find and delete duplicate files by content.")
    p.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        default=True,
        help="Search directories recursively (default: True).",
    )
    p.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        default=False,
        help="Don't delete; just show what would be done.",
    )
    p.add_argument(
        "--follow-symlinks",
        action="store_true",
        default=False,
        help="Follow symlinks to files.",
    )
    p.add_argument(
        "--min-size",
        type=int,
        default=1,
        help="Minimum file size (bytes) to consider. Default 1 (skip zero-size).",
    )
    p.add_argument(
        "-k",
        "--keep",
        choices=("first", "oldest", "newest"),
        default="oldest",
        help="Which file to keep within duplicates.",
    )
    p.add_argument("--workers", type=int, default=8, help="Number of worker threads (default: 8).")
    args = p.parse_args()
    root = Path.cwd()
    print("Phase 1: Scanning files and grouping by size...")
    size_groups = defaultdict(list)
    total_files = 0
    for f in iter_files(root, args.recursive, args.follow_symlinks, args.min_size):
        total_files += 1
        try:
            size = f.stat().st_size
            size_groups[size].append(f)
        except OSError:
            continue
    candidates = {s: lst for s, lst in size_groups.items() if len(lst) > 1}
    if not candidates:
        print(f"Scanned {total_files} files. No potential duplicates found.")
        return
    candidate_count = sum((len(v) for v in candidates.values()))
    print(f"Phase 1 complete: {candidate_count} files in {len(candidates)} size-groups to examine.")
    print("Phase 2: Quick hash comparison...")
    quick_groups = defaultdict(list)
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {}
        for files in candidates.values():
            for fpath in files:
                futures[ex.submit(quick_hash, fpath)] = fpath
        for fut in as_completed(futures):
            fpath = futures[fut]
            try:
                h = fut.result()
                key = (fpath.stat().st_size, h)
                quick_groups[key].append(fpath)
            except Exception as e:
                print(f"Warning: Skipping {fpath}: {e}")
    need_full = [group for group in quick_groups.values() if len(group) > 1]
    if not need_full:
        print("No duplicates found after quick hash comparison.")
        return
    full_candidates = sum((len(g) for g in need_full))
    print(f"Phase 2 complete: {full_candidates} files in {len(need_full)} groups need full hash.")
    print("Phase 3: Full hash comparison...")
    full_groups = defaultdict(list)
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {}
        for group in need_full:
            for fpath in group:
                st_key = file_stat_key(fpath)
                futures[ex.submit(full_hash, fpath)] = (fpath, st_key)
        for fut in as_completed(futures):
            fpath, st_key = futures[fut]
            try:
                h, _ = fut.result()
                if h:
                    full_groups[h].append((fpath, st_key))
            except Exception as e:
                print(f"Warning: Skipping {fpath}: {e}")
    print("Phase 4: Processing results...")
    to_delete = []
    for h, entries in full_groups.items():
        if len(entries) < 2:
            continue
        inode_map = defaultdict(list)
        for p, stk in entries:
            inode_map[stk].append(p)
        group_reps = [min(ps, key=str) for ps in inode_map.values()]
        if len(group_reps) < 2:
            continue
        keep_file = choose_keep(group_reps, policy=args.keep)
        for rep in group_reps:
            if rep != keep_file:
                to_delete.append(rep)
    if not to_delete:
        print("No duplicate files found.")
        return
    print(f"\nFound {len(to_delete)} duplicate files to delete.")
    if not args.dry_run:
        print("Files to be deleted:")
    else:
        print("DRY RUN - Files that would be deleted:")
    for p in to_delete:
        try:
            rel_path = p.relative_to(cwd)
        except ValueError:
            rel_path = p
        print(f"  {rel_path}")
    if args.dry_run:
        print(f"\nDry-run complete. {len(to_delete)} files would be deleted.")
        return
    try:
        response = input(f"\nDelete {len(to_delete)} files? [y/N]: ").strip().lower()
        if response not in ("y", "yes"):
            print("Deletion cancelled.")
            return
    except (KeyboardInterrupt, EOFError):
        print("\nDeletion cancelled.")
        return
    removed = 0
    failed = 0
    freed_space = 0
    for p in to_delete:
        try:
            size = p.stat().st_size
            p.unlink()
            freed_space += size
            removed += 1
            try:
                print(f"Deleted: {p.relative_to(cwd)} ({size:,} bytes)")
            except ValueError:
                print(f"Deleted: {p} ({size:,} bytes)")
        except OSError as e:
            failed += 1
            try:
                print(f"Failed: {p.relative_to(cwd)} - {e}")
            except ValueError:
                print(f"Failed: {p} - {e}")
    print(f"\nSummary:")
    print(f"  Files scanned: {total_files}")
    print(f"  Duplicates found: {len(to_delete)}")
    print(f"  Successfully deleted: {removed}")
    if failed:
        print(f"  Failed to delete: {failed}")
    if freed_space:
        print(f"  Space freed: {freed_space:,} bytes ({freed_space / 1024 / 1024:.2f} MB)")


if __name__ == "__main__":
    main()
