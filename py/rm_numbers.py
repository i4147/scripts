#!/data/data/com.termux/files/usr/bin/python
import os
import re
from multiprocessing import Pool
from pathlib import Path
from typing import Optional

_RE_UNDERSCORE: re.Pattern[str] = re.compile(r"_\d+")
_RE_PAREN: re.Pattern[str] = re.compile(r"\(\d+\)")


def _clean_stem(stem: str) -> str:
    stem = _RE_UNDERSCORE.sub("", stem)
    stem = _RE_PAREN.sub("", stem)
    return stem.replace(" ", "_")


def _candidate(base: Path, stem: str, suffix: str, index: int) -> Path:
    if index == 0:
        return base / f"{stem}{suffix}"
    return base / f"{stem}_{index}{suffix}"


def _reserve(path: Path) -> bool:
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
        os.close(fd)
        return True
    except FileExistsError:
        return False


def _process(args: tuple[str, str]) -> Optional[tuple[str, str]]:
    path_str, root_str = args
    path = Path(path_str)
    if path.is_symlink() or not path.is_file():
        return None
    stem = _clean_stem(path.stem)
    suffix = path.suffix
    if f"{stem}{suffix}" == path.name:
        return None
    base = Path(root_str)
    index = 0
    while True:
        target = _candidate(base, stem, suffix, index)
        if target != path and _reserve(target):
            break
        index += 1
        if index > 100_000:
            return None
    os.replace(path, target)
    return (path.name, target.name)


def main() -> list[tuple[str, str]]:
    root = Path.cwd()
    args = [(str(p), str(p.parent)) for p in root.rglob("*") if p.is_file() and not p.is_symlink()]
    with Pool() as pool:
        results = pool.map(_process, args)
    return [r for r in results if r is not None]


if __name__ == "__main__":
    for old, new in main():
        print(f"{old} -> {new}")
