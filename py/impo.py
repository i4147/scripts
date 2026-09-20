import os
from collections import deque
from multiprocessing import Pool
from pathlib import Path
from sys import exit
from time import perf_counter

import dh


def process_dir(fp):
    if not fp.exists():
        return False
    print(f"[OK] {fp.name}")
    cmd = "imports"
    os.chdir(fp)
    return dh.run(cmd)


def main() -> None:
    start = perf_counter()
    dr = "/data/data/com.termux/files/usr/lib/python3.12/site-packages"
    drs = []
    for pth in os.listdir(dr):
        path = Path(os.path.join(dr, pth))
        if path.is_dir() and not path.name.endswith("dist-info"):
            drs.append(path)
    with Pool(8) as p:
        pending = deque()
        for f in drs:
            pending.append(p.apply_async(process_dir, ((f),)))
            if len(pending) > 16:
                pending.popleft().get()
        while pending:
            pending.popleft().get()
    print(f"{perf_counter() - start} seconds")


if __name__ == "__main__":
    exit(main())
