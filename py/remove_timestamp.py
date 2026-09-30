from pathlib import Path
import re


def remove_timestamp(filename: str) -> str:
    """
    Remove timestamp pattern like _2026070965435 from end of filename (before extension).
    Pattern: underscore followed by 13 digits, right before the extension.
    """
    p = Path(filename)
    stem = p.stem
    new_stem = re.sub(r"_\d{13}$", "", stem)
    if new_stem != stem:
        return new_stem + p.suffix
    return None  # signal: no change


def unique_path(path: Path) -> Path:
    """
    If path exists, append _1, _2, ... before the extension until free.
    """
    if not path.exists():
        return path

    parent = path.parent
    stem = path.stem
    suffix = path.suffix

    # If stem already ends with _N, strip it so we don't stack counters
    base_stem = re.sub(r"_\d+$", "", stem)

    i = 1
    while True:
        candidate = parent / f"{base_stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def strip_timestamps(root: str = "."):
    root_path = Path(root).resolve()
    files = [f for f in root_path.rglob("*") if f.is_file()]

    renamed = 0
    renamed_conflict = 0
    skipped = 0

    for file_path in files:
        new_name = remove_timestamp(file_path.name)
        if new_name is None:
            continue

        target = file_path.with_name(new_name)
        final = unique_path(target)

        try:
            file_path.rename(final)
            if final != target:
                print(f"[OK*]  {file_path.name}  ->  {final.name}  (conflict)")
                renamed_conflict += 1
            else:
                print(f"[OK]   {file_path.name}  ->  {final.name}")
                renamed += 1
        except OSError as e:
            print(f"[ERR]  {file_path}: {e}")
            skipped += 1

    print(f"\nDone. Renamed: {renamed}, Renamed w/ conflict: {renamed_conflict}, Skipped: {skipped}")


if __name__ == "__main__":
    strip_timestamps(".")
