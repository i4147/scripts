import pathlib
import sys
from time import perf_counter


def main() -> None:
    cleaned = []
    start = perf_counter()
    with pathlib.Path("urls.txt").open(encoding="utf-8") as f:
        lines = f.readlines()
        for line in lines:
            if ".jpg" not in line and ".jpeg" not in line and ".png" not in line and ".svg" not in line:
                if ".gif" not in line and ".webp" not in line:
                    cleaned.append(line)
    with pathlib.Path("urls.txt").open("w", encoding="utf-8") as fo:
        fo.writelines(cleaned)
    print(f"{perf_counter() - start} sec")


if __name__ == "__main__":
    sys.exit(main())
