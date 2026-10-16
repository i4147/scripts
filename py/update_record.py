import pathlib
import sys
from time import perf_counter

from rignore import walk


def process_record(fp) -> None:
    print(f"processing ...  {fp}")
    lines = []
    new_lines = []
    with pathlib.Path(fp).open(encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
        new_lines.extend(line for line in lines if ".whl" not in line.lower())
    with pathlib.Path(fp).open("w", encoding="utf-8") as fo:
        fo.writelines(new_lines)


def main() -> None:
    start = perf_counter()
    dir = "/data/data/com.termux/files/usr/lib/python3.12/site-packages"
    for path in walk(dir):
        if path.is_dir() or path.is_symlink():
            continue
        if path.is_file() and path.name == "RECORD" and "dist-info" in str(path):
            process_record(path)
    print(f"{perf_counter() - start} sec")


if __name__ == "__main__":
    sys.exit(main())
