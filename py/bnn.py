from __future__ import annotations
import sys
from pathlib import Path
from dh import mpf3, get_nobinary


def process_file(path) -> None:
    path = Path(path)
    content = path.read_text(encoding="utf-8")
    new_content = content.replace("\\n", "\n")
    if new_content != content:
        path.write_text(content, encoding="utf-8")
        print(f"{path.name} updated.")


def main():
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = [Path(p) for p in args] if args else get_nobinary(cwd)
    mpf3(process_file, files)


if __name__ == "__main__":
    main()
