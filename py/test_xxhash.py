import sys
from pathlib import Path

from dh import get_files
from pbar import Pbar
from xxhash import (
    xxh3_64,
    xxh3_128,
    xxh32,
    xxh32_digest,
    xxh32_hexdigest,
    xxh32_intdigest,
    xxh64,
    xxh64_digest,
    xxh64_hexdigest,
    xxh64_intdigest,
    xxh128,
)


def process_file(fp) -> None:
    funcs = [
        xxh32,
        xxh64,
        xxh64_digest,
        xxh64_intdigest,
        xxh64_hexdigest,
        xxh3_64,
        xxh3_128,
    ]
    data = fp.read_bytes()
    h32 = xxh32()
    h32.update(data)
    h64 = xxh64()
    h64.update(data)
    h128 = xxh128()
    h128.update(data)
    h3_64 = xxh3_64()
    h3_64.update(data)
    h3_128 = xxh3_128()
    h3_128.update(data)
    print(f"{h32.hexdigest()}")
    print(f"{xxh32_hexdigest(data)}")
    print(f"{xxh32_intdigest(data)}")
    print(f"{xxh32_digest(data)}")
    print(f"{h64.hexdigest()}")
    print(f"{h128.hexdigest()}")
    print(f"{h3_64.hexdigest()}")
    input("?")


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]
    if args:
        for arg in args:
            p = Path(arg)
            if p.is_file():
                files.append(p)
            if p.is_dir():
                files.extend(get_files(p))
    else:
        files = get_files(cwd)
    with Pbar("") as pbar:
        for f in pbar.wrap(files):
            process_file(f)


if __name__ == "__main__":
    sys.exit(main())
