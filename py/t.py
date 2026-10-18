from __future__ import annotations
import sys
from pathlib import Path
from fastwalk import walk_files


def process_file(path):
    path = Path(path)
    try:
        data = path.read_text(encoding="utf-8")
        res = exec(compile(source=data, filename=str(path), mode="exec"))
        exec(data)
    except OSError:
        pass


def main():
    cwd = Path.home() / "isaac"
    for path in walk_files(cwd):
        if path.suffix == ".py":
            process_file(path)


if __name__ == "__main__":
    sys.exit(main())
