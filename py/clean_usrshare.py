import sys
from time import perf_counter

import dh
import rignore


def main() -> None:
    to_del = (
        "news",
        "copyright",
        "changelog",
        "author",
        "authors",
        "license",
        "licence",
        "readme",
        "bugs",
        "changes",
        "copying",
    )
    ext = (
        ".c",
        ".py",
        ".cpp",
        ".h",
        ".hpp",
        ".sh",
        ".vim",
        ".js",
        ".json",
        ".css",
    )
    start = perf_counter()
    dir = "/data/data/com.termux/files/usr/share"
    for pth in rignore.walk(dir):
        path = dh.Path(pth)
        if path.is_file() or path.is_symlink():
            if path.exists() and any(x in path.stem.lower() for x in to_del):
                if not any(x == path.suffix for x in ext):
                    path.unlink()
                    print(f"{path.name} is removed")
    print(f"{perf_counter() - start} sec")


if __name__ == "__main__":
    sys.exit(main())
