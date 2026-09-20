from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import xxhash


def file_hash(path, block_size: int = 32768) -> str | None:
    h = xxhash.xxh64()
    try:
        with path.open("rb") as f:
            while True:
                chunk = f.read(block_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except OSError as e:
        print(f"Error hashing {path}: {e}")
        return None


def find_duplicates_parallel(files_to_hash, max_workers=None):
    hash_map = defaultdict(list)
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {executor.submit(file_hash, f): f for f in files_to_hash}
        for future in as_completed(future_to_file):
            file = future_to_file[future]
            try:
                h = future.result()
                if h:
                    hash_map[h].append(file)
            except Exception as e:
                print(f"Error processing {file}: {e}")
    return hash_map


def get_files(root_path):
    found = []
    for r, d, files in root_path.walk():
        for f in files:
            path = Path(r) / f
            if path.is_symlink():
                continue
            if ".git" in path.parts:
                continue
            if path.is_file():
                found.append(path)
    return sorted(found)


def find_and_delete_dups(root: Path = Path.cwd(), max_workers=8) -> None:
    size_groups = defaultdict(list)
    for f in get_files(root):
        try:
            size = f.stat().st_size
            size_groups[size].append(f)
        except OSError as e:
            print(f"Error accessing {f}: {e}")
    files_to_hash = []
    for size, files in size_groups.items():
        if len(files) > 1:
            files_to_hash.extend(files)
    print(f"Hashing {len(files_to_hash)} potential duplicate files...")
    hash_map = find_duplicates_parallel(files_to_hash, max_workers=max_workers)
    duplicates_to_delete = []
    for h, files in hash_map.items():
        if len(files) > 1:
            files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            duplicates_to_delete.extend(files[1:])
            print(f"Found duplicate set for hash {h[:8]}...: {[str(f) for f in files]}")
    if duplicates_to_delete:
        print(f"\nDeleting {len(duplicates_to_delete)} duplicate files (keeping the newest of each set)...")
        deleted_count = 0
        for dup in duplicates_to_delete:
            try:
                dup.unlink()
                print(f"Deleted: {dup}")
                deleted_count += 1
            except OSError as e:
                print(f"Failed to delete {dup}: {e}")
        print(f"\nFinished. {deleted_count} duplicates removed.")
    else:
        print("\nNo duplicate files found.")


if __name__ == "__main__":
    find_and_delete_dups(max_workers=8)
