from collections import deque
from multiprocessing import Pool
from pathlib import Path
from sys import exit

from dh import get_files


def process_file(fp) -> None:
    seen = set()
    nl = []
    with fp.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            if "lambda " in line and not line in seen:
                nl.append(line)
                seen.add(line)
                print(f"[{fp.name}] --> {line}")
    with Path("/sdcard/lambda").open("a", encoding="utf-8") as fo:
        fo.writelines(nl)


def main() -> None:
    root_dir = Path("/data/data/com.termux")
    files = get_files(root_dir, extensions=[".py", ".pyx", ".pyi", ".pxd"])
    with Pool(8) as p:
        pending = deque()
        for f in files:
            pending.append(p.apply_async(process_file, ((f),)))
            if len(pending) > 16:
                pending.popleft().get()
        while pending:
            pending.popleft().get()
    print("[5;96m of n e")


if __name__ == "__main__":
    exit(main())
