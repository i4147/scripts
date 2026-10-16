import pathlib
import sys
from time import perf_counter


def main() -> None:
    start = perf_counter()
    cc = []
    with pathlib.Path("im").open(encoding="utf-8") as f:
        lines = f.readlines()
        cc.extend(line for line in lines if "==NA" in line)
    with pathlib.Path("im").open("w", encoding="utf-8") as fo:
        fo.writelines(cc)
    print(f"{perf_counter() - start} seconds")


if __name__ == "__main__":
    sys.exit(main())
