import os
from pathlib import Path


def mkdeb(fp: Path) -> None:
    pardir = fp.parent
    os.chdir(pardir)
    os.system(f"dpkg-deb -b {str(fp)} {fp.stem}.deb")


if __name__ == "__main__":
    cwd = Path.cwd()
    for f in cwd.iterdir():
        if f.is_dir():
            mkdeb(f)
