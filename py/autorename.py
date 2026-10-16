import os
from pathlib import Path


def common_prefix(strings: list[Path]) -> str:
    return os.path.commonprefix(str(strings))


def common_suffix(strings: list[Path]) -> str:
    return os.path.commonprefix([s[::-1] for s in str(strings)])[::-1]


if __name__ == "__main__":
    cwd = Path.cwd()
    files = [f for f in cwd.glob("*.srt")]
    prefix = common_prefix(files)
    suffix = common_suffix(files)
    for p in files:
        core = str(p)[len(prefix) : len(str(p)) - len(suffix)]
        core = core.strip(".")
        new_name = f"{p.stem.split('.')[0]}.{core}.{p.suffix}"
        p.rename(new_name)
