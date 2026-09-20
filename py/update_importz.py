from collections import deque
from multiprocessing import Pool
from pathlib import Path
from sys import exit
from time import perf_counter

from fastwalk import walk_files


def process_file(fp) -> bool:
    if not fp.exists():
        return False
    cleaned = []
    with Path(fp).open(encoding="utf-8") as f:
        lines = f.readlines()
        cleaned.extend(
            line.rstrip().replace("Not Installed", "").replace("(NA)", "").replace("(unknown)", "").replace("==", "")
            for line in lines
            if line
        )
    with Path(fp).open("w", encoding="utf-8") as fo:
        fo.writelines(str(k) + "\n" for k in cleaned)
    print(f"{fp} updated")
    return True


def main() -> None:
    start = perf_counter()
    files = []
    dir = "/data/data/com.termux/files/usr/lib/python3.12/site-packages"
    for pth in walk_files(dir):
        path = Path(pth)
        if path.is_symlink():
            continue
        if path.is_file() and path.name == "importz.txt":
            files.append(path)
    with Pool(8) as p:
        pending = deque()
        for f in files:
            pending.append(p.apply_async(process_file, ((f),)))
            if len(pending) > 16:
                pending.popleft().get()
        while pending:
            pending.popleft().get()
    print(f"{perf_counter() - start} seconds")


if __name__ == "__main__":
    exit(main())
