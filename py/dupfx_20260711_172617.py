
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from os import scandir
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
        msg = "error hashing file"
        raise OSError(msg)
    return h.hexdigest()


def full_hash(path: Path, block_size: int = DEFAULT_BLOCK) -> str:
    h = xxh64()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(block_size), b""):
                h.update(chunk)
    except Exception as e:
        msg = "error hashing file"
        raise OSError(msg)
    return h.hexdigest()


def iter_files(root: Path):

    with scandir(root) as it:
        for entry in it:
            path = Path(entry.path)
            if ".git" in path.parts or path.is_symlink():
                continue
            if path.is_file() and not path.is_symlink():
                if path.stat().st_size:
                    yield path


def choose_keep(files, policy="oldest"):
    if policy == "first":
        return min(files, key=str)
    if policy == "oldest":
        return min(files, key=lambda p: p.stat().st_mtime)
    if policy == "newest":
        return max(files, key=lambda p: p.stat().st_mtime)
    return min(files, key=str)


def main() -> None:
    cwd = Path.cwd()
    size_groups = defaultdict(list)
    total_files = 0
    for f in iter_files(cwd):
        total_files += 1
        try:
            size_groups[f.stat().st_size].append(f)
        except Exception:
            continue
    candidates_by_size = {s: lst for s, lst in size_groups.items() if len(lst) > 1}
    if not candidates_by_size:
        print("No potential duplicates found (no groups with equal size).")
        return
    print(
        f"Found {sum((len(v) for v in candidates_by_size.values()))} files in {len(candidates_by_size)} size-groups to examine."
    )
    quick_groups = defaultdict(list)
    with ThreadPoolExecutor(max_workers=16) as ex:
        futures = {}
        for files in candidates_by_size.values():
            for fpath in files:
                futures[ex.submit(quick_hash, fpath)] = fpath
        for fut in as_completed(futures):
            fpath = futures[fut]
            try:
                h = fut.result()
                key = (fpath.stat().st_size, h)
                quick_groups[key].append(fpath)
            except Exception as e:
                print(f"Skipping {fpath}: {e}")
    need_full = [group for group in quick_groups.values() if len(group) > 1]
    if not need_full:
        print("No dups")
        return
    full_groups = defaultdict(list)
    with ThreadPoolExecutor(max_workers=16) as ex:
        futures = {}
        for group in need_full:
            for fpath in group:
                st_key = file_stat_key(fpath)
                futures[ex.submit(full_hash, fpath)] = (fpath, st_key)
        for fut in as_completed(futures):
            fpath, st_key = futures[fut]
            try:
                h = fut.result()
                full_groups[h].append((fpath, st_key))
            except Exception as e:
                print(f"Skipping {fpath}: {e}")
    to_delete = []
    for h, entries in full_groups.items():
        inode_map = {}
        for p, stk in entries:
            inode_map.setdefault(stk, []).append(p)
        group_reps = [min(ps) for ps in inode_map.values()]
        if len(group_reps) < 2:
            continue
        keep_file = choose_keep(group_reps, policy="oldest")
        for ps in group_reps:
            if ps == keep_file:
                continue
            to_delete.append(ps)
    if not to_delete:
        print("No dups")
        return
    print(f"Planned deletions: {len(to_delete)} files.")
    for p in to_delete:
        print("  " + str(p))
    removed = 0
    failed = 0
    for p in to_delete:
        try:
            p.unlink()
            print(f"Deleted: {p.relative_to(cwd)}")
            removed += 1
        except Exception as e:
            print(f"Failed to delete {p.relative_to(cwd)}: {e}")
            failed += 1
    if failed:
        print(f"Removed: {removed}. Failed: {failed}.")
    else:
        print(f"Removed: {removed}")


if __name__ == "__main__":
    main()
