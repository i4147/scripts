
import os
import sys
from pathlib import Path
from collections import defaultdict
from multiprocessing import Pool, cpu_count

import xxhash




NUM_WORKERS = 8
SKIP_DIR_NAMES = {".git"}
HASH_CHUNK_SIZE = 1 << 20  
MAX_DEPTH = 64  





def _file_hash(path: Path) -> str:
    h = xxhash.xxh64()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(HASH_CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def _should_skip_dir(p: Path) -> bool:
    return p.name in SKIP_DIR_NAMES


def _collect_files(root: Path):
    result = []
    root = root.resolve()
    stack = [(root, 0)]
    while stack:
        cur, depth = stack.pop()
        if depth > MAX_DEPTH:
            continue
        try:
            entries = list(os.scandir(cur))
        except (PermissionError, OSError):
            continue
        for entry in entries:
            try:
                
                if entry.is_symlink():
                    
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if entry.name in SKIP_DIR_NAMES:
                        continue
                    stack.append((Path(entry.path), depth + 1))
                elif entry.is_file(follow_symlinks=False):
                    rel = Path(entry.path).relative_to(root).as_posix()
                    result.append((rel, Path(entry.path)))
            except OSError:
                continue
    return result


def folder_signature(root: Path):
    root = root.resolve()

    
    files = _collect_files(root)

    
    
    
    
    
    if not files:
        return None

    
    direct_files = [(rel, abs_) for rel, abs_ in files if "/" not in rel]

    
    
    if not direct_files:
        return None

    
    rel_paths = sorted(rel for rel, _ in files)
    struct_h = xxhash.xxh64()
    for rp in rel_paths:
        struct_h.update(rp.encode("utf-8"))
        struct_h.update(b"\x00")

    
    content_h = xxhash.xxh64()
    for rel, abs_path in sorted(files, key=lambda x: x[0]):
        try:
            fh = _file_hash(abs_path)
        except (PermissionError, OSError):
            fh = "unreadable"
        content_h.update(rel.encode("utf-8"))
        content_h.update(b"\x00")
        content_h.update(fh.encode("ascii"))
        content_h.update(b"\x01")

    return (
        root.name,
        struct_h.hexdigest(),
        content_h.hexdigest(),
        str(root),
    )





def find_all_folders(start: Path):
    start = start.resolve()
    folders = []
    stack = [(start, 0)]
    while stack:
        cur, depth = stack.pop()
        if depth > MAX_DEPTH:
            continue
        folders.append(cur)
        try:
            entries = list(os.scandir(cur))
        except (PermissionError, OSError):
            continue
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if entry.name in SKIP_DIR_NAMES:
                        continue
                    stack.append((Path(entry.path), depth + 1))
            except OSError:
                continue
    return folders





def main():
    start = Path.cwd()
    print(f"Scanning: {start}")
    print(f"Workers : {NUM_WORKERS}")

    folders = find_all_folders(start)
    print(f"Found {len(folders)} folder(s) (pre-filter).")

    results = []

    
    with Pool(processes=NUM_WORKERS) as pool:
        async_results = [pool.apply_async(folder_signature, (f,)) for f in folders]
        for ar in async_results:
            try:
                res = ar.get()
            except Exception as e:
                
                print(f"[warn] worker error: {e}", file=sys.stderr)
                continue
            if res is not None:
                results.append(res)

    
    
    
    groups = defaultdict(list)
    for name, struct_h, content_h, path in results:
        groups[(struct_h, content_h)].append(path)

    duplicates = {k: v for k, v in groups.items() if len(v) > 1}

    if not duplicates:
        print("\nNo duplicate folders found.")
        return

    print(f"\nFound {len(duplicates)} set(s) of duplicate folders:\n")
    for i, (_, paths) in enumerate(sorted(duplicates.items(), key=lambda kv: kv[1][0]), start=1):
        print(f"--- Group {i} ({len(paths)} folders) ---")
        for p in sorted(paths):
            print(f"  {p}")
        print()


if __name__ == "__main__":
    main()
