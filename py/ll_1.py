import datetime
import os
import shutil
import stat
import sys
from pathlib import Path

REVERSE = "-r" in sys.argv


def fsz(sz):
    sz = abs(int(sz))
    if sz < 1024:
        return f"{sz} B"
    units = ("K", "M", "G", "T", "P")
    i = -1
    v = float(sz)
    while v >= 1024 and i < len(units) - 1:
        v /= 1024
        i += 1
    if v < 10:
        s = f"{v:.1f}"
        s = s.removesuffix(".0")
    else:
        s = f"{int(v)}"
    return f"{s} {units[i]}B"


def gsz(path):
    try:
        st = os.lstat(path)
    except OSError:
        return 0
    mode = st.st_mode
    if stat.S_ISLNK(mode):
        return st.st_size
    if stat.S_ISREG(mode):
        return st.st_size
    if not stat.S_ISDIR(mode):
        return 0
    total = 0
    seen = set()
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        est = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    emode = est.st_mode
                    if stat.S_ISLNK(emode):
                        total += est.st_size
                    elif stat.S_ISREG(emode):
                        key = (est.st_dev, est.st_ino)
                        if key in seen:
                            continue
                        seen.add(key)
                        total += est.st_size
                    elif stat.S_ISDIR(emode):
                        stack.append(entry.path)
        except OSError:
            continue
    return total


def fmt_time(ts):
    return datetime.datetime.fromtimestamp(ts).strftime("%H:%M")


def visible_len(s):
    n = 0
    i = 0
    L = len(s)
    while i < L:
        c = s[i]
        if c == "\x1b":
            j = s.find("m", i)
            if j == -1:
                break
            i = j + 1
            continue
        n += 1
        i += 1
    return n


def truncate(s, width):
    if width <= 0:
        return ""
    if len(s) <= width:
        return s
    if width == 1:
        return "…"
    return s[: width - 1] + "…"


def main():
    cwd = Path.cwd()
    term_w = shutil.get_terminal_size(fallback=(80, 24)).columns
    dirz = []
    otherz = []
    entries = [p for p in cwd.iterdir()]
    for entry in entries:
        p = Path(entry)
        try:
            st = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        try:
            if entry.is_dir():
                size = gsz(p)
                dirz.append((p, size, st.st_ctime))
            else:
                if stat.S_ISLNK(st.st_mode):
                    size = st.st_size
                else:
                    size = st.st_size
                otherz.append((p, size, st.st_ctime))
        except OSError:
            continue
    otherz.sort(key=lambda t: t[1], reverse=REVERSE)
    dirz.sort(key=lambda t: t[0].name.lower(), reverse=REVERSE)
    SIZE_W = 8
    TIME_W = 5
    fixed = SIZE_W + TIME_W + 4
    name_w = max(10, term_w - fixed)
    TIME_COLOR = "\x1b[38;2;255;127;80m"

    def emit(name, size, ctime, name_color):
        size_str = fsz(size)
        size_col = size_str.rjust(SIZE_W)
        t = fmt_time(ctime)
        name_disp = truncate(name, name_w)
        pad = name_w - visible_len(name_disp)
        pad = max(pad, 0)
        print(f"\x1b[05;{name_color}m{name_disp}\x1b[0m{' ' * pad} \x1b[05;96m{size_col}\x1b[0m {TIME_COLOR}{t}\x1b[0m")

    for p, sz, ct in otherz:
        name = p.name
        try:
            mode = p.stat(follow_symlinks=False).st_mode
        except OSError:
            mode = 0
        if mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
            emit(name, sz, ct, "92")
        else:
            emit(name, sz, ct, "96")
    for p, sz, ct in dirz:
        emit(p.name, sz, ct, "94")


if __name__ == "__main__":
    main()
