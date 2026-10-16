import os
from pathlib import Path
from sys import exit
from time import perf_counter


def process_dir(fp: Path) -> bool:
    if len(os.listdir(fp)) == 1:
        print(fp)
        return True
    return False


def main() -> None:
    perf_counter()
    for pth in os.listdir("."):
        path = Path(pth)
        if path.is_dir():
            process_dir(path)


if __name__ == "__main__":
    exit(main())
