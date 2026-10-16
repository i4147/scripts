import pathlib
import sys
from time import perf_counter


def main() -> None:
    start = perf_counter()
    cleaned = []
    with pathlib.Path("sp2.txt").open(encoding="utf-8") as f:
        lines = f.readlines()
        for line in lines:
            if ".pth" not in line:
                cleaned.append(line)
                print(line)
    with pathlib.Path("sp2.txt").open("w", encoding="utf-8") as fo:
        fo.writelines(cleaned)
    print(f"{len(cleaned)} lines saved")
    print(f"{perf_counter() - start} sec")


if __name__ == "__main__":
    sys.exit(main())
