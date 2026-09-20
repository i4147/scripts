from __future__ import annotations

import datetime
import sys
from os import scandir as _scandir
from pathlib import Path

REVERSE = "-r" in sys.argv


def fsz(sz: float) -> str:
    sz = abs(int(sz))
    units = ("", "K", "M", "G", "T")
    if sz == 0:
        return "0 B"
    i = min(int(int(sz).bit_length() - 1) // 10, len(units) - 1)
    sz /= 1024**i
    return f"{int(sz)} {units[i]}B"


def gsz(path: str | Path) -> int:
    path = Path(path)
    total_size = 0
    if not path.exists():
        return 0
    if path.is_file():
        try:
            total_size = path.stat().st_size
        except OSError:
            return 0
    elif path.is_dir():
        for entry in _scandir(path):
            try:
                if Path(entry.path).is_symlink() or not Path(entry.path).exists():
                    continue
                if entry.is_file():
                    total_size += entry.stat().st_size
                elif entry.is_dir():
                    total_size += gsz(entry.path)
            except OSError:
                continue
    return total_size


if __name__ == "__main__":
    cwd = Path.cwd()
    dirz = []
    otherz = []
    sz = ""
    for path in sorted(cwd.glob("*"), key=lambda e: e.stat().st_size, reverse=REVERSE):
        if not path.exists():
            continue
        if path.is_dir():
            dirz.append(path)
        else:
            otherz.append(path)
    for f in otherz:
        ctime = datetime.datetime.fromtimestamp(f.stat().st_ctime).strftime("%H:%M")
        if f.is_symlink():
            print(f"\x1b[05;95m{f.name[:24]:25}\x1b[0m", end=" ")
        else:
            sz = str(fsz(gsz(f)))
            match len(sz):
                case 3:
                    sz = "      " + sz
                case 4:
                    sz = "     " + sz
                case 5:
                    sz = "    " + sz
                case 6:
                    sz = "   " + sz
                case 7:
                    sz = "  " + sz
                case 8:
                    sz = " " + sz
            print(f"\x1b[05;92m{f.stem[:20] + f.suffix:25}\x1b[0m", end=" ")
        print(f"\x1b[05;96m{sz}\x1b[0m", end=" ")
        print(f"\x1b[05;93m{ctime}\x1b[0m")
    for dr in sorted(dirz):
        ctime = datetime.datetime.fromtimestamp(dr.stat().st_ctime).strftime("%H:%M")
        sz = str(fsz(gsz(dr)))
        if len(sz) == 7:
            sz = "  " + sz
        if len(sz) == 8:
            sz = " " + sz
        print(f"\x1b[05;94m{dr.name[:24]:25}\x1b[0m", end=" ")
        print(f"\x1b[05;96m{sz}\x1b[0m", end=" ")
        print(f"\x1b[05;93m{ctime}\x1b[0m")
