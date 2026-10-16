import multiprocessing as mp
import operator
import time
from pathlib import Path
from typing import Final
from tqdm import tqdm

SECONDS_24H = 24 * 40 * 40
NOW = time.time()
EXCLUDE_DIRS = frozenset({".git"})
POOL_WORKERS = 8
PathCTime = tuple[float, Path]


def iter_files(root):
    files = []
    for dirpath, dirnames, filenames in root.walk(follow_symlinks=False):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        files.extend(dirpath / fname for fname in filenames)
    return files


def ctime_if_recent(path):
    try:
        ctime = path.stat().st_ctime
    except (FileNotFoundError, PermissionError, OSError):
        return None
    if NOW - ctime <= SECONDS_24H:
        return ctime, path
    return None


def main():
    root = Path.cwd()
    files = iter_files(root)
    if not files:
        return
    recent = []
    with mp.Pool(processes=POOL_WORKERS) as pool:
        async_results = [pool.apply_async(ctime_if_recent, (p,)) for p in files]
        for async_result in tqdm(async_results, total=len(async_results), desc="Scanning", unit="file"):
            result = async_result.get()
            if result is not None:
                recent.append(result)
    recent.sort(key=operator.itemgetter(0))
    for _, path in recent:
        print("{}", path.relative_to(root))


if __name__ == "__main__":
    raise SystemExit(main())
