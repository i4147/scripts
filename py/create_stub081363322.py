from __future__ import annotations

from os import path
import sys
from pathlib import Path
from dh import mpf3, get_files
from subprocess import run


def process_file(path) -> None:
    path = Path(path)
    print(f"processing {path.name}")
    cmd = ["stubgen", "--verbose", str(path)]
    stubfile = path.with_suffix(".pyi")
    if stubfile.exists:
        return
    ret = run(cmd, check=True, check_output=True)
    if ret:
        print(f"[ERROR] {path.name}")
    else:
        print(f"[OK] {path.name}")


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]

    files = [Path(p) for p in args] if args else get_files(cwd, ext=[".py"])
    if len(files) == 1:
        process_file(files[0])
        sys.exit(0)

    mpf3(process_file, files)
    stubless = []
    for f in files:
        stubpath = f.with_suffix(".pyi")
        if not stubpath.exists():
            stubless.append(f)
    if stubless:
        for k in stubless:
            print(f" - {k.name}")


if __name__ == "__main__":
    sys.exit(main())
