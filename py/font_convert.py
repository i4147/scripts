import argparse
import sys
from functools import partial
from pathlib import Path
from dh import cprint, get_files, mpf3, unique_path
from fontTools.ttLib import TTFont

FONT_EXTS = [".ttf", ".otf", ".woff", ".woff2"]
FLAVORS = {"woff": "woff", "woff2": "woff2", "ttf": None}


def convert(path, to="woff2", remove_source=False):
    path = Path(path)
    target = path.with_suffix(f".{to}")
    if target.exists() and target.stat().st_size:
        target = unique_path(target)
    try:
        font = TTFont(path)
        font.flavor = FLAVORS[to]
        font.save(target)
    except Exception as exc:
        cprint(f"error converting {path.name}: {exc}")
        return
    print(f"{path.name} -> {target.name}")
    if remove_source and path.exists():
        path.unlink()


def collect(paths, to):
    files = []
    for p in paths:
        if p.is_dir():
            files.extend(get_files(p, ext=FONT_EXTS))
        elif p.exists():
            files.append(p)
        else:
            cprint(f"not found: {p}")
    if not files:
        files = get_files(Path.cwd(), ext=FONT_EXTS)
    return [f for f in files if f.suffix.lower() != f".{to}"]


def main():
    ap = argparse.ArgumentParser(description="Convert TTF/OTF/WOFF/WOFF2 fonts to another container flavour.")
    ap.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="font files or directories (default: scan the current directory)",
    )
    ap.add_argument(
        "--to",
        required=True,
        choices=sorted(FLAVORS),
        help="target format/extension",
    )
    ap.add_argument(
        "-r",
        "--rm",
        action="store_true",
        help="delete the source file after a successful conversion",
    )
    args = ap.parse_args()
    files = collect(args.paths, args.to)
    if not files:
        cprint(f"no font files to convert to .{args.to}")
        return sys.exit(1)
    worker = partial(convert, to=args.to, remove_source=args.rm)
    if len(files) == 1:
        worker(files[0])
        return
    mpf3(worker, files)


if __name__ == "__main__":
    raise SystemExit(main())
