import sys
from collections import deque
from multiprocessing import Pool
from pathlib import Path

from dh import get_files

MAX_QUEUE = 16


def process_file(fp) -> bool | None:
    if not fp.exists():
        return False
    ext = fp.suffix
    if "js" in ext or "min" in ext or "css" in ext:
        print(f"{fp.name} : {ext}")
    return None


def main() -> None:
    root_dir = Path.cwd()
    args = sys.argv[1:]
    files = [Path(arg) for arg in args] if args else get_files(root_dir, recursive=True)
    with Pool(8) as pool:
        pending = deque()
        for f in files:
            pending.append(pool.apply_async(process_file, (f,)))
            if len(pending) > MAX_QUEUE:
                pending.popleft().get()
        while pending:
            pending.popleft().get()


if __name__ == "__main__":
    sys.exit(main())
