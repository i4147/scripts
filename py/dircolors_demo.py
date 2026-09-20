import pathlib
from sys import exit
from time import perf_counter

from dh import BIN_EXT, TXT_EXT


def main() -> None:
    start = perf_counter()
    ext = TXT_EXT
    ext.update(BIN_EXT)
    if not pathlib.Path("dircolora").exists():
        pathlib.Path("dircolors").mkdir()
    for e in ext:
        fn = f"dircolors/file_name{e}"
        pathlib.Path(fn).write_text("", encoding="utf-8")
    print(f"{perf_counter() - start} seconds")


if __name__ == "__main__":
    exit(main())
