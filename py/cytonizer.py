import os
import sys
from os import chdir as os_chdir
from pathlib import Path
from dh import get_files, mpf3

START_DIR = Path.cwd()
NUM_PROCESSES = 4


def process_file(path):
    path = Path(path)
    pardir = path.parent
    os_chdir(pardir)
    os.system(f"cythonize {path.name}")


def main():
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = []
    if args:
        for arg in args:
            p = Path(arg)
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                files.extend(get_files(p, ext=[".pyx"]))
    else:
        files = get_files(cwd, ext=[".pyx"])
    _ = mpf3(process_file, files)


if __name__ == "__main__":
    raise SystemExit(main())
