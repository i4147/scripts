import mmap
import re
import sys
from pathlib import Path

MMAP_THRESHOLD = 1024 * 1024
ANSI_RE = re.compile(
    rb"""
    \x1b\[[0-9;]*[A-Za-z] |
    \x1b\][^\x07]*\x07   |
    \x1b[=>]
    """,
    re.VERBOSE,
)
CONTROL_RE = re.compile(rb"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]")
MULTI_NL_RE = re.compile(rb"\n{3,}")


def remove_backspaces(data: bytes) -> bytes:
    out = bytearray()
    for b in data:
        if b == 0x08:
            if out:
                out.pop()
        else:
            out.append(b)
    return bytes(out)


def clean(data: bytes) -> bytes:
    data = ANSI_RE.sub(b"", data)
    data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    data = remove_backspaces(data)
    data = CONTROL_RE.sub(b"", data)
    return MULTI_NL_RE.sub(b"\n\n", data)


def read_file(path: Path) -> bytes:
    size = path.stat().st_size
    if size < MMAP_THRESHOLD:
        return path.read_bytes()
    with (
        Path(path).open("rb") as f,
        mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm,
    ):
        return mm[:]


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("Usage: cleaner <file>")
    path = Path(sys.argv[1])
    if not path.exists():
        sys.exit(f"Error: file not found: {path}")
    original = read_file(path)
    cleaned = clean(original)
    path.write_bytes(cleaned)
    print(f"{path.stem} cleaned.")


if __name__ == "__main__":
    main()
