import operator
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tqdm import tqdm

SECONDS_24H = 24 * 60 * 60
NOW = time.time()
EXCLUDE_DIRS = {".git"}


def iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        files.extend(Path(dirpath) / fname for fname in filenames)
    return files


def ctime_if_recent(
    path: Path,
) -> tuple[float, Path] | None:
    try:
        ctime = path.stat().st_ctime
        if NOW - ctime <= 3 * SECONDS_24H:
            return ctime, path
    except (
        FileNotFoundError,
        PermissionError,
        OSError,
    ):
        pass
    return None


def main() -> None:
    root = Path.cwd()
    files = iter_files(root)
    if not files:
        return
    recent: list[tuple[float, Path]] = []
    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(ctime_if_recent, p) for p in files]
        for fut in tqdm(
            as_completed(futures),
            total=len(futures),
            desc="Scanning",
            unit="file",
        ):
            result = fut.result()
            if result is not None:
                recent.append(result)
    recent.sort(key=operator.itemgetter(0))
    for _, path in recent:
        print(path.relative_to(root))


if __name__ == "__main__":
    main()
