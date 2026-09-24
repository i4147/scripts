from __future__ import annotations

from pathlib import Path

from dh import gsz, rrs, runcmd
from fastwalk import walk_files


def process_file(path) -> None:
    path = Path(path)
    if "lazy" in path.parts:
        return
    before = gsz(path)
    if not before or len(path.read_text().splitlines()) == 1:
        return
    try:
        runcmd(["svgo", str(path)], show_output=True)
        after = gsz(path)
        rrs(path, before, after)
        return
    except:
        return


def main() -> None:
    cwd = Path.cwd()
    for f in walk_files(cwd):
        if f.suffix in {".svg", ".SVG"}:
            process_file(f)


if __name__ == "__main__":
    raise SystemExit(main())
