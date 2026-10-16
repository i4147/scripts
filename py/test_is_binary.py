from pathlib import Path

from binaryornot import is_binary as isb1
from dh import cprint, get_files
from dh import is_binary as isb2

if __name__ == "__main__":
    cwd = Path.home() / "tmp"
    files = get_files(cwd)
    flen = len(files)
    cprint(f"{flen} files found")
    c = 0
    for path in files:
        c += 1
        cprint(f"{c}/{flen}")
        if ".git" in path.parts or "__pycache__" in path.parts:
            continue
        r1 = isb1(path)
        r2 = isb2(path)
        if r1 != r2:
            cprint(f"{path.relative_to(cwd)}: dh result:{r2} binaryornotresult:{r1}")
