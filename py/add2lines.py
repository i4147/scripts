from collections import deque
from multiprocessing import get_context
from pathlib import Path
from sys import argv, exit

from dh import format_size, get_files, get_size

MAX_QUEUE = 16


def process_file(fp) -> None:
    nl = []
    lines = []
    with Path(fp).open("r", encoding="utf-8") as f:
        lines = f.readlines()
    nl.extend(("from dh import ", "import pytest\n"))
    nl.extend(lines)
    with Path(fp).open("w", encoding="utf-8") as fo:
        fo.writelines(nl)


def main() -> None:
    cwd = Path.cwd()
    before = get_size(cwd)
    args = argv[1:]
    if args:
        files = [Path(f) for f in args]
    else:
        files = get_files(cwd, recursive=True)
    with get_context("spawn").Pool(8) as pool:
        pending = deque()
        for f in files:
            pending.append(pool.apply_async(process_file, (f,)))
            if len(pending) > MAX_QUEUE:
                pending.popleft().get()
        while pending:
            pending.popleft().get()
    diff_size = before - get_size(cwd)
    print(f"space saved : {format_size(diff_size)}")


if __name__ == "__main__":
    exit(main())
