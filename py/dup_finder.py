from pathlib import Path

from xxhash import xxh64


def file_xxhash(path, block_size=32768) -> str:
    h = xxh64()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(block_size), b""):
            h.update(chunk)
    return h.hexdigest()


def find_and_delete_dups() -> None:
    cwd = Path.cwd()
    size_groups = {}
    for f in cwd.rglob("*"):
        if f.is_file() and not f.is_symlink():
            size_groups.setdefault(f.stat().st_size, []).append(f)
    seen = {}
    duplicates = []
    for files in size_groups.values():
        if len(files) < 2:
            continue
        for f in files:
            h = file_xxhash(f)
            if h in seen:
                duplicates.append(f)
            else:
                seen[h] = f
    for dup in duplicates:
        try:
            dup.unlink()
            print(f"Deleted duplicate: {dup.name}")
        except Exception as e:
            print(f"Failed to delete {dup.name}: {e}")
    print(f"Finished. {len(duplicates)} duplicates removed.")


if __name__ == "__main__":
    find_and_delete_dups()
