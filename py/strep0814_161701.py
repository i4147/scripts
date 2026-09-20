import sys
from collections.abc import Callable
from pathlib import Path

from dh import cprint, fsz, get_files, gsz, mpf3, runcmd


def process_file(path) -> None:
    path = Path(path)
    before = path.stat().st_size
    _ret, _, _ = runcmd(["strip", str(path)], show_output=True)
    after = path.stat().st_size
    if not after:
        return
    dz = before - after
    if dz:
        cprint(f"{path.name} | ratio: {after / before:.1f}%")


if __name__ == "__main__":
    cwd = Path.cwd()
    before = gsz(cwd)
    args = sys.argv[1:]
    files = (
        [Path(p) for p in args]
        if args
        else get_files(
            cwd,
            ext=[
                ".so",
                ".SO",
                ".so.1",
                ".so.0",
                ".so.2",
                ".so.2400",
                ".so.2400.0.0",
                ".so.0.0",
                ".so.0.1",
                ".so.1.0",
                ".so.0.0.0",
            ],
        )
    )
    mpf3(process_file, files)
    after = gsz(cwd)
    dsz = before - after
    if dsz:
        print(f"space freed: {fsz(dsz)}")
