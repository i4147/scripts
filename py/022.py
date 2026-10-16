import pathlib
from sys import exit
from time import perf_counter


def process_file(fp: str) -> None:
    nl = []
    with pathlib.Path(fp).open(encoding="utf-8") as f:
        lines = f.readlines()
        for line in lines:
            if line.startswith("Ukl") or len(line) < 20:
                continue
            nl.append(line)
    with pathlib.Path(fp).open("w", encoding="utf-8") as fo:
        fo.writelines(nl)


def main() -> None:
    start = perf_counter()
    process_file("02")
    print(f"{perf_counter() - start} seconds")


if __name__ == "__main__":
    exit(main())
