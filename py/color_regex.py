import builtins
import contextlib
import re
import sys
from pathlib import Path
from time import perf_counter
import fastwalk

txt_file = Path("/sdcard/txt").open(encoding="utf-8")
EXT = [p.strip() for p in txt_file]
txt_file.close()
print(len(EXT))
color_regex = re.compile("[#][a-fA-F0-9]{6}")


def process_file(fpath: Path):
    print(f"processing {fpath}")
    with Path(fpath).open(encoding="utf-8", errors="ignore") as f:
        return color_regex.findall(f.read())


def process_binary(fpath: Path):
    print(f"processing {fpath}")
    with Path(fpath).open("rb") as fb:
        return color_regex.findall(fb.read())


def main() -> None:
    start = perf_counter()
    uniq = []
    matches = []
    for pth in fastwalk.walk_files("/data/data/com.termux"):
        path = Path(pth)
        if path.is_symlink():
            continue
        if path.is_file() and any((x == path.suffix[1:] for x in EXT)):
            matches.extend(process_file(path))
        if path.is_file() and (not path.suffix):
            with contextlib.suppress(builtins.BaseException):
                matches.extend(process_binary(path))
    uniq = list(set(matches))
    with Path("/sdcard/colors").open("a", encoding="utf-8") as fo:
        fo.write("\n")
        fo.writelines((k + "\n" for k in uniq))
    print(f"{perf_counter() - start} sec")


if __name__ == "__main__":
    sys.exit(main())
