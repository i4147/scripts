from __future__ import annotations

import sys
from pathlib import Path

import htmlmin
from dh import get_files, mpf3


def process_file(path: str | Path) -> None:
    path = Path(path)
    try:
        orig = path.read_text(encoding="utf-8")
        code = htmlmin.minify(orig, remove_comments=True)
        if len(code) != len(orig):
            path.write_text(code, encoding="utf-8")
            print(f"[OK] {path.name}")
            return
    except Exception:
        print(f"[ERR] {path.name}")
        return


def main() -> None:
    cwd = Path.cwd()
    files = get_files(cwd, ext=[".html", ".htm", ".xhtml", ".mhtml"])
    if len(files) == 1:
        process_file(files[0])
        sys.exit(1)
    mpf3(process_file, files)


if __name__ == "__main__":
    main()
