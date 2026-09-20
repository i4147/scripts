
import stat
from multiprocessing import Pool, cpu_count
from pathlib import Path

DIR_PERM = 493
FILE_PERM = 436
SKIP_NAMES = {".git", "__pycache__", "bin", "sbin", "libexec"}


def is_executable(mode: int) -> bool:
    return bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))


def is_binary(file_path: Path) -> bool:
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(512)
        return b"\x00" in chunk
    except OSError:
        return False


def has_shebang(file_path: Path) -> bool:
    try:
        with open(file_path, "rb") as f:
            first_line = f.readline()
        return first_line.startswith(b"#!")
    except OSError:
        return False


def process_path(path: Path) -> None:
    try:
        current_mode = stat.S_IMODE(path.stat().st_mode)
        if path.is_dir():
            if current_mode != DIR_PERM:
                path.chmod(DIR_PERM)
                print(f"[DIR]  {path}  {oct(current_mode)} -> {oct(DIR_PERM)}")
            return
        if is_executable(current_mode) and (is_binary(path) or has_shebang(path)):
            return
        if current_mode != FILE_PERM:
            path.chmod(FILE_PERM)
            print(f"[FILE] {path}  {oct(current_mode)} -> {oct(FILE_PERM)}")
    except PermissionError:
        print(f"[SKIP] Permission denied: {path}")
    except FileNotFoundError:
        pass
    except OSError as e:
        print(f"[ERR]  {path}: {e}")


def collect_paths(cwd: str) -> list[Path]:
    root = Path(cwd).resolve()
    paths = []
    for p in root.rglob("*"):
        if any(part in SKIP_NAMES for part in p.parts):
            continue
        paths.append(p)
    return paths


def normalize_permissions(cwd: str) -> None:
    print(f"Collecting paths under {cwd} ...")
    all_paths = collect_paths(cwd)
    total = len(all_paths)
    print(f"Found {total} items. Processing with {cpu_count()} workers...")
    with Pool(processes=cpu_count()) as pool:
        for _ in pool.imap_unordered(process_path, all_paths, chunksize=500):
            pass
    print("Done.")


if __name__ == "__main__":
    normalize_permissions(".")
