import os
import subprocess
from sys import exit
from time import perf_counter


def process_file(fp: str) -> None:
    fp = str(fp).replace(".zip", "")
    subprocess.run(["uzp", fp], check=True)


def main() -> None:
    start = perf_counter()
    for pth in os.listdir("."):
        if pth.endswith(".zip"):
            process_file(pth)
    print(f"{perf_counter() - start} seconds")


if __name__ == "__main__":
    exit(main())
