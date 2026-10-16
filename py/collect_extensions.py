from pathlib import Path
from sys import exit

from dh import BIN_EXT, TXT_EXT, gext


def get_files(dr: Path | str):
    path = Path(dr)
    for item in path.iterdir():
        if item.exists() and item.is_file():
            yield item
        if item.exists() and item.is_dir():
            yield from get_files(item)


def main() -> None:
    extensions = []
    seen = set(TXT_EXT | BIN_EXT)
    print(len(seen))
    directories = (
        "/data/data/com.termux",
        "/sdcard",
    )
    for directory in directories:
        for path in get_files(directory):
            if path.is_symlink():
                continue
            if path.is_file():
                ext = gext(path)
                if ext and ext not in seen:
                    extensions.append(ext)
                    seen.add(ext)
                    print(ext)
    print(f"{len(extensions)} extensions found.")
    Path("/sdcard/new_ext").write_text("\n".join(list(extensions)), encoding="utf-8")


if __name__ == "__main__":
    exit(main())
