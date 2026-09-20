from collections import deque
from multiprocessing import Pool
from pathlib import Path
from sys import exit
from time import perf_counter

from dh import TXT_EXT
from fastwalk import walk_files
from termcolor import cprint

EXT = {
    ".sh",
    ".json",
    ".list",
    ".py",
    ".pyi",
    ".pyx",
    ".c",
    ".rs",
    ".cpp",
    ".h",
    ".hpp",
    ".txt",
    ".md",
    ".js",
    ".ts",
    ".html",
    ".jsx",
    ".tsx",
    ".cc",
    ".rst",
}


def is_really_binary(path: Path, blocksize: int = 4096) -> bool:
    try:
        with path.open("rb") as f:
            chunk = f.read()
        if not chunk:
            return False
        if b"\x00" in chunk:
            return True
        text_chars = bytearray(range(32, 127)) + b"\n\r\t\b"
        nontext = sum(1 for b in chunk if b not in text_chars)
        percentage = nontext / len(chunk)
        if percentage > 0.3:
            print(f"[\u2713] {path.suffix} {path.stat().st_size}: {percentage}")
        for encoding in (
            "utf-8",
            "utf-16",
            "utf-32",
        ):
            try:
                chunk.decode(encoding)
                return False
            except (
                UnicodeDecodeError,
                LookupError,
            ):
                continue
        return percentage > 0.30
    except Exception:
        return True


def process_file(fp) -> bool | None:
    if not fp.exists():
        return False
    if fp.suffix in EXT:
        return True
    if is_really_binary(fp):
        cprint(f"{fp.suffix} is binary", "yellow")
        return True
    else:
        cprint(
            f"[\u2714] {fp.name} : {fp.stat().st_size}",
            "cyan",
        )
    return None


def main() -> None:
    start = perf_counter()
    files = []
    for pth in walk_files("/data/data/com.termux"):
        path = Path(pth)
        if path.is_symlink() or path.stat().st_size == 0:
            continue
        if path.is_file() and path.suffix in TXT_EXT:
            files.append(path)
    with Pool(8) as p:
        pending = deque()
        for f in files:
            pending.append(p.apply_async(process_file, ((f),)))
            if len(pending) > 16:
                pending.popleft().get()
        while pending:
            pending.popleft().get()
    print(f"{perf_counter() - start} seconds")


if __name__ == "__main__":
    exit(main())
