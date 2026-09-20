import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

MAX_WORKERS = os.cpu_count() or 4
TEXT_CHUNK = 8192
EXCLUDED_DIRS = {".git"}
WHITELIST_FILE = Path("text_based.txt")


def load_extension_whitelist() -> set[str]:
    if not WHITELIST_FILE.exists():
        sys.exit("Error: text_based.txt not found")
    exts = set()
    for line in WHITELIST_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip().lower()
        if line and (not line.startswith("#")):
            exts.add(f".{line.lstrip('.')}")
    return exts


def is_text_file(path: Path) -> bool:
    try:
        with Path(path).open("rb") as f:
            return b"\x00" not in f.read(TEXT_CHUNK)
    except OSError:
        return False


def clean_lines(lines: list[str], collapse: bool) -> tuple[list[str], int]:
    removed = 0
    if not collapse:
        cleaned = [l for l in lines if l.strip()]
        removed = len(lines) - len(cleaned)
        return (cleaned, removed)
    cleaned = []
    blank_run = 0
    for line in lines:
        if line.strip():
            blank_run = 0
            cleaned.append(line)
        else:
            blank_run += 1
            if blank_run == 1:
                cleaned.append(line)
            else:
                removed += 1
    return (cleaned, removed)


def clean_file(path: Path, whitelist: set[str], collapse: bool) -> tuple[bool, int, str]:
    if path.suffix.lower() not in whitelist:
        return (False, 0, "")
    if not is_text_file(path):
        return (False, 0, "")
    try:
        with Path(path).open(encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        cleaned, removed = clean_lines(lines, collapse)
        if removed == 0:
            return (False, 0, "")
        with Path(path).open("w", encoding="utf-8", errors="ignore") as f:
            f.writelines(cleaned)
        return (True, removed, path.suffix.lower())
    except Exception:
        return (False, 0, "")


def iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for name in filenames:
            yield (Path(dirpath) / name)


def main() -> None:
    collapse = "--collapse" in sys.argv
    whitelist = load_extension_whitelist()
    root = Path.cwd()
    total_removed = 0
    modified_files = 0
    per_ext = defaultdict(int)
    files = list(iter_files(root))
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(clean_file, f, whitelist, collapse): f for f in files}
        for future in as_completed(futures):
            changed, removed, ext = future.result()
            if changed:
                modified_files += 1
                total_removed += removed
                per_ext[ext] += removed
    print("✓ done")
    print(f"  files modified: {modified_files}")
    print(f"  blank lines removed: {total_removed}")
    if per_ext:
        print("\n  per-extension:")
        for ext, count in sorted(per_ext.items()):
            print(f"    {ext}: {count}")


if __name__ == "__main__":
    main()
