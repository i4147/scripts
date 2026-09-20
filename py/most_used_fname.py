from collections import Counter
from pathlib import Path
from sys import exit
from time import perf_counter

from fastwalk import walk_files


def process_file(fp):
    return fp.exists()


def main() -> None:
    start = perf_counter()
    files = []
    for pth in walk_files("/data/data/com.termux/files/usr/share"):
        path = Path(pth)
        if path.is_symlink():
            continue
        if path.is_file():
            files.append(path.name)
    counter = Counter(files)
    for k in counter:
        if counter.get(k) > 2:
            print(f"{k}:{counter.get(k)}")
    print(f"{perf_counter() - start} seconds")


if __name__ == "__main__":
    exit(main())
