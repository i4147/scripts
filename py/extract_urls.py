import pathlib
import sys
from time import perf_counter

import dh


def main() -> None:
    start = perf_counter()
    nl = [line for line in dh.read_lines("urls.txt") if line.strip().endswith(".html")]
    with pathlib.Path("html_urls").open("w", encoding="utf-8") as f:
        f.writelines(nl)
    print(f"{perf_counter() - start} seconds")


if __name__ == "__main__":
    sys.exit(main())
