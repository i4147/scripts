import shutil
from pathlib import Path
from sys import exit
from time import perf_counter

from fastwalk import walk_dirs


def main() -> None:
    start = perf_counter()
    dir = "/data/data/com.termux/files/usr/lib/python3.12/site-packages"
    for pth in walk_dirs(dir):
        path = Path(pth)
        if path.is_symlink():
            continue
        if (
            path.is_dir()
            and path.name == "tests"
            and not any(
                str1 in path.name
                for str1 in (
                    "numpy",
                    "setuptools",
                    "pip",
                    "wheel",
                    "packaging",
                    "pandas",
                )
            )
        ):
            shutil.rmtree(path)
            print(f"{path} removed.")
    print(f"{perf_counter() - start} seconds")


if __name__ == "__main__":
    exit(main())
