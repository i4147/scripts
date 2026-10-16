import os
from pathlib import Path


def main():
    cwd = Path.cwd()
    for r, _, files in os.walk(cwd):
        for f in files:
            if f.startswith("__init__.py") or f.endswith("py.typed"):
                continue
            path = Path(r) / f
            if path.is_symlink():
                continue
            if path.is_file() and not path.stat().st_size:
                print(path.relative_to(cwd))


if __name__ == "__main__":
    raise SystemExit(main())
