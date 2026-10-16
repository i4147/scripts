import shutil
from os import listdir
from pathlib import Path
from sys import exit
from time import perf_counter


def process_dir(fp: Path) -> bool:
    return bool(fp.exists() and not fp.is_symlink() and fp.is_dir() and len(listdir(fp)) == 1)


def main() -> None:
    perf_counter()
    dirs = []
    for pth in listdir("."):
        path = Path(pth)
        if path.is_file() or path.is_symlink():
            continue
        if path.is_dir() and process_dir(path):
            dirs.append(path)
    for d in dirs:
        tp = f"/data/data/com.termux/files/home/tmp/0/3/{d.name}"
        shutil.move(d, tp)


if __name__ == "__main__":
    exit(main())
