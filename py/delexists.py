import os
import pathlib
from sys import exit
from time import perf_counter


def main() -> None:
    start = perf_counter()
    dir1 = "bin"
    dir2 = "/data/data/com.termux/files/usr/bin"
    files1 = os.listdir(dir1)
    files2 = os.listdir(dir2)
    for f in files1:
        if f in files2:
            path = f"bin/{f}"
            pathlib.Path(path).unlink()
            print(f"{dir2}/{f} exists")
    print(f"{perf_counter() - start} seconds")


if __name__ == "__main__":
    exit(main())
