import os
from pathlib import Path
from dh import get_files


def exdeb(fp: Path) -> None:
    pardir = fp.parent
    os.chdir(pardir)
    os.system(f"dpkg-deb --raw-extract {str(fp)} {fp.stem}")


if __name__ == "__main__":
    cwd = Path.cwd()
    files = get_files(cwd, extensions=[".deb"])
    for f in files:
        exdeb(f)
