import os
from sys import exit
from time import perf_counter


def process_file(fp: str) -> None:
    try:
        with open(fp, encoding="utf-8") as f:
            line = f.readline()
            if not line.startswith("#!/data/data/com.termux/files/usr/bin/python"):
                print(fp)
    except:
        pass


def main() -> None:
    start = perf_counter()
    for pth in os.listdir("."):
        if not os.path.islink(pth):
            process_file(pth)
    print(f"{perf_counter() - start} seconds")


if __name__ == "__main__":
    exit(main())
