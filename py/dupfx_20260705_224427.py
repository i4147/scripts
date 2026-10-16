from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from dh import cprint, fsz, gsz
from xxhash import xxh64

CHUNK_SIZE = 32768


def should_skip(path: Path) -> bool:
    return bool(
        path.is_symlink()
        or not (size := path.stat().st_size)
        or any(pat in path.parts for pat in (".git", "__pycache__", ".mypy_cache", ".ruff_cache"))
    )


def get_hash_file(path: Path) -> tuple[str, Path]:
    path = Path(path)
    if not path.exists() or not (size := path.stat().st_size):
        return "", path
    h = xxh64()
    try:
        with path.open("rb") as f:
            while chunk := f.read(CHUNK_SIZE):
                h.update(chunk)
        return h.hexdigest(), path
    except (OSError, IOError):
        return "", path


def find_duplicates() -> None:
    cwd = Path.cwd()
    files_by_hash = defaultdict(list)
    duplicate_count = 0
    total_size = 0
    files_with_sizes = []
    for path in cwd.rglob("*"):
        if path.is_file() and not should_skip(path):
            try:
                if size := path.stat().st_size:
                    files_with_sizes.append((path, size))
            except OSError as e:
                print(f"Error getting size for {path}: {e}")
                continue
    files_by_size = defaultdict(list)
    for path, size in files_with_sizes:
        files_by_size[size].append(path)
    paths_to_hash = []
    for size, paths in files_by_size.items():
        if (count := len(paths)) > 1:
            paths_to_hash.extend(paths)
    print(f"Scanning {len(paths_to_hash)} files for duplicates...")
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_path = {executor.submit(get_hash_file, path): path for path in paths_to_hash}
        for future in as_completed(future_to_path):
            if hash_result := future.result()[0]:
                path = future.result()[1]
                files_by_hash[hash_result].append(path)
    for hash_val, paths in files_by_hash.items():
        if (count := len(paths)) > 1:
            duplicate_count += count - 1
            print(f"\nHash {hash_val}:")
            for file_path in paths:
                relative_path = file_path.relative_to(cwd)
                cprint(f"  - {relative_path}", "cyan")
                total_size += gsz(file_path)
    if duplicate_count > 0:
        print(f"\n{'=' * 50}")
        cprint(f"Removing {duplicate_count} duplicate files...", "yellow")
        for hash_val, paths in files_by_hash.items():
            if (count := len(paths)) > 1:
                for file_path in paths[1:]:
                    relative_path = file_path.relative_to(cwd)
                    cprint(f"  - {relative_path} removed", "yellow")
                    try:
                        file_path.unlink()
                    except OSError as e:
                        print(f"  Error removing {relative_path}: {e}")
    print(f"\n{'=' * 50}")
    cprint(f"Total duplicates found: {duplicate_count}", "cyan")
    cprint(f"Total size of duplicates: {fsz(total_size)}", "cyan")
    cprint(f"Space saved: {fsz(total_size)}", "green")


if __name__ == "__main__":
    find_duplicates()
