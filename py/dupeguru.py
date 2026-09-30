#!/data/data/com.termux/files/home/.local/bin/python
"""dupeGuru-style CLI duplicate file finder.

Fast, multiprocessing, hash-based duplicate detection.

By default this is a DRY RUN: it only reports what would be deleted.
Pass -a / --apply to actually remove the duplicate files.
"""

from __future__ import annotations

import argparse
import hashlib
import multiprocessing as mp
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Iterator

CHUNK_SIZE = 1 << 20  # 1 MiB read buffer
PARTIAL_SIZE = 1 << 16  # first 64 KiB used for the cheap "partial" hash
DIGEST_BYTES = 16  # blake2b digest size


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def human_size(n: int) -> str:
    x = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if x < 1024 or unit == "PiB":
            return f"{int(x)} B" if unit == "B" else f"{x:.2f} {unit}"
        x /= 1024
    return f"{n} B"


def walk_files(roots: Iterable[Path], follow_symlinks: bool = False) -> Iterator[Path]:
    for root in roots:
        try:
            if root.is_file():
                yield root
                continue
            if not root.is_dir():
                continue
        except OSError:
            continue
        for dirpath, _dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
            for name in filenames:
                p = Path(dirpath) / name
                if not follow_symlinks and p.is_symlink():
                    continue
                try:
                    if p.is_file():
                        yield p
                except OSError:
                    continue


# --------------------------------------------------------------------------- #
# hashing worker (must be top-level to be picklable by mp.Pool)
# --------------------------------------------------------------------------- #


def _hash_worker(task: tuple[str, int | None]) -> tuple[str, str, int, str | None]:
    """Return (path, hexdigest, bytes_read, error).  limit=None -> full file."""
    path, limit = task
    try:
        h = hashlib.blake2b(digest_size=DIGEST_BYTES)
        read = 0
        with open(path, "rb") as f:
            while True:
                if limit is not None and read >= limit:
                    break
                want = CHUNK_SIZE if limit is None else min(CHUNK_SIZE, limit - read)
                buf = f.read(want)
                if not buf:
                    break
                h.update(buf)
                read += len(buf)
        return path, h.hexdigest(), read, None
    except OSError as exc:
        return path, "", 0, str(exc)


# --------------------------------------------------------------------------- #
# core
# --------------------------------------------------------------------------- #


def find_duplicates(
    roots: list[Path],
    workers: int,
    min_size: int,
    follow_symlinks: bool,
    log,
) -> list[list[Path]]:
    # ---- Stage 1: bucket by exact size -------------------------------------
    by_size: dict[int, list[Path]] = defaultdict(list)
    seen_inodes: set[tuple[int, int]] = set()
    n_files = 0

    for p in walk_files(roots, follow_symlinks):
        try:
            st = p.stat()
        except OSError:
            continue
        n_files += 1
        if st.st_size < min_size:
            continue
        key = (st.st_dev, st.st_ino)
        if key in seen_inodes:  # skip hard-links / duplicate roots
            continue
        seen_inodes.add(key)
        by_size[st.st_size].append(p)

    log(f"Scanned {n_files} file(s).")

    # Any file whose size is unique cannot possibly have a duplicate.
    size_groups = {s: ps for s, ps in by_size.items() if len(ps) > 1}
    if not size_groups:
        return []

    size_of: dict[str, int] = {}
    partial_tasks: list[tuple[str, int | None]] = []
    for size, paths in size_groups.items():
        for p in paths:
            sp = str(p)
            size_of[sp] = size
            partial_tasks.append((sp, PARTIAL_SIZE))

    log(f"{len(partial_tasks)} candidate(s) share a size; partial-hashing...")

    # ---- Stage 2: partial hash (cheap, filters most non-dupes) -------------
    partial_groups: dict[tuple[int, str], list[Path]] = defaultdict(list)
    with mp.Pool(processes=workers) as pool:
        for path, digest, _read, err in pool.imap_unordered(_hash_worker, partial_tasks, chunksize=32):
            if err:
                log(f"WARN: {path}: {err}")
                continue
            partial_groups[(size_of[path], digest)].append(Path(path))

    # ---- Stage 3: full hash for surviving collisions -----------------------
    full_tasks: list[tuple[str, int | None]] = []
    for paths in partial_groups.values():
        if len(paths) > 1:
            full_tasks.extend((str(p), None) for p in paths)

    if not full_tasks:
        return []

    log(f"{len(full_tasks)} candidate(s) share a partial hash; full-hashing...")

    full_groups: dict[tuple[int, str], list[Path]] = defaultdict(list)
    with mp.Pool(processes=workers) as pool:
        for path, digest, size, err in pool.imap_unordered(_hash_worker, full_tasks, chunksize=1):
            if err:
                log(f"WARN: {path}: {err}")
                continue
            full_groups[(size, digest)].append(Path(path))

    return [paths for paths in full_groups.values() if len(paths) > 1]


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="dupefinder",
        description="Find (and optionally delete) duplicate files.",
    )
    ap.add_argument("paths", nargs="+", type=Path, help="Files or directories to scan")
    ap.add_argument("-a", "--apply", action="store_true", help="Delete the duplicates (default: dry run)")
    ap.add_argument(
        "-j", "--workers", type=int, default=os.cpu_count() or 1, help="Number of worker processes (default: CPU count)"
    )
    ap.add_argument(
        "-m", "--min-size", type=int, default=1, help="Ignore files smaller than this many bytes (default: 1)"
    )
    ap.add_argument("--follow-symlinks", action="store_true", help="Follow symlinks when walking directories")
    ap.add_argument("-q", "--quiet", action="store_true", help="Suppress progress messages")
    args = ap.parse_args(argv)

    for p in args.paths:
        if not p.exists():
            print(f"error: path does not exist: {p}", file=sys.stderr)
            return 2

    def log(msg: str) -> None:
        if not args.quiet:
            print(msg, file=sys.stderr)

    log(f"Scanning {len(args.paths)} root(s) with {args.workers} worker(s)...")

    groups = find_duplicates(
        roots=list(args.paths),
        workers=max(1, args.workers),
        min_size=args.min_size,
        follow_symlinks=args.follow_symlinks,
        log=log,
    )

    if not groups:
        print("No duplicates found.")
        return 0

    # Pre-compute totals so the printout is stable.
    prepared: list[tuple[list[Path], int]] = []
    total_redundant = 0
    total_bytes = 0
    for paths in groups:
        paths.sort()
        try:
            sz = paths[0].stat().st_size
        except OSError:
            sz = 0
        prepared.append((paths, sz))
        total_redundant += len(paths) - 1
        total_bytes += sz * (len(paths) - 1)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(
        f"=== {mode}: {len(prepared)} group(s), {total_redundant} redundant "
        f"file(s), {human_size(total_bytes)} reclaimable ===\n"
    )

    removed = 0
    reclaimed = 0
    for i, (paths, sz) in enumerate(prepared, 1):
        print(f"[Group {i}]  {human_size(sz)} each")
        print(f"  KEEP     {paths[0]}")
        for p in paths[1:]:
            if args.apply:
                try:
                    p.unlink()
                    print(f"  REMOVED  {p}")
                    removed += 1
                    reclaimed += sz
                except OSError as exc:
                    print(f"  FAILED   {p}  ({exc})", file=sys.stderr)
            else:
                print(f"  REMOVE   {p}")
        print()

    if args.apply:
        print(f"Removed {removed} file(s), reclaimed {human_size(reclaimed)}.")
    else:
        print(f"Dry run complete. Re-run with -a/--apply to delete {total_redundant} file(s).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
