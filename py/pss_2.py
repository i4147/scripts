import mmap
import multiprocessing as mp
import os
import sys
from pathlib import Path

CSV_PATH = Path("/sdcard/data/pip.csv")

PARALLEL_MIN_BYTES = 4 * 1024 * 1024
MAX_WORKERS = 8


def _scan_range(args):
    path, start, end, kw = args
    matches = []

    with open(path, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            if start > 0:
                nl = mm.find(b"\n", start)
                if nl == -1:
                    return matches
                start = nl + 1

            if end < size:
                nl = mm.find(b"\n", end)
                end = size if nl == -1 else nl + 1

            if start >= end:
                return matches

            chunk = mm[start:end]

    for line in chunk.split(b"\n"):
        if not line:
            continue
        comma = line.find(b",")
        if comma <= 0:
            continue
        name = line[:comma]
        if kw in name.lower():
            try:
                dl = int(line[comma + 1 :])
            except ValueError:
                continue
            matches.append((name.decode("utf-8"), dl))

    return matches


def _split_ranges(path, n):
    size = os.path.getsize(path)
    step = size // n
    ranges = []
    for i in range(n):
        start = i * step
        end = size if i == n - 1 else (i + 1) * step
        ranges.append((str(path), start, end))
    return ranges


def main():
    if len(sys.argv) > 1:
        keyword = sys.argv[1]
    else:
        keyword = input("Search package: ").strip()
        if not keyword:
            print("No keyword given.")
            return

    kw = keyword.lower().encode()

    size = os.path.getsize(CSV_PATH)
    workers = min(mp.cpu_count(), MAX_WORKERS)

    if size < PARALLEL_MIN_BYTES or workers <= 1:
        matches = _scan_range((str(CSV_PATH), 0, size, kw))
    else:
        tasks = [(p, s, e, kw) for (p, s, e) in _split_ranges(CSV_PATH, workers)]

        with mp.Pool(workers) as pool:
            results = pool.map(_scan_range, tasks)
        matches = [item for sub in results for item in sub]

    if not matches:
        print(f"No matches for '{keyword}'.")
        return

    matches.sort(key=lambda x: x[1], reverse=True)
    for name, dl in matches:
        print(f"{name}  {dl}")


if __name__ == "__main__":
    main()
