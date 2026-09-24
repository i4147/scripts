import sys
from collections import deque
from pathlib import Path

CHUNK_SIZE = 32768
from collections.abc import Callable, Iterable
from pathlib import Path


def mpf_joblib(process_function: Callable, files: list[Path], **kwargs):
    from joblib import Parallel, delayed

    file_strings = [str(f) for f in files]
    return Parallel(n_jobs=-1)((delayed(process_function)(file_str, **kwargs) for file_str in file_strings))


mpf3 = mpf_joblib


def get_files(path: str | Path, ext: list[str] | None = None) -> list[Path]:
    path = Path(path)
    skip_dirs = {".git", "__pycache__"}
    queue = deque([path])
    files = []
    while queue:
        current = queue.popleft()
        try:
            entries = current.iterdir()
        except (PermissionError, OSError):
            continue
        for item in entries:
            if item.is_symlink():
                continue
            if item.is_dir() and item.name not in skip_dirs:
                queue.append(item)
            elif item.is_file():
                if ext is None or item.suffix in ext:
                    files.append(item)
    return files


def is_binary(path: Path | str) -> bool:
    path = Path(path)
    try:
        with path.open("rb") as f:
            chunk = f.read(CHUNK_SIZE)
        if not chunk:
            return False
        if b"\x00" in chunk:
            return True
        text_chars = bytearray(range(32, 127)) + b"\n\r\t\x08"
        nontext = sum((1 for b in chunk if b not in text_chars))
        return nontext / len(chunk) > 0.3
    except Exception:
        return True


from dh import get_nobinary


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


def process_file(path: Path, collapse: bool) -> tuple[bool, int, str]:
    print(f"processing {path.name}")
    path = Path(path)
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


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = [Path(p) for p in args] if args else get_nobinary(cwd)
    mpf3(process_file, files)


if __name__ == "__main__":
    main()
