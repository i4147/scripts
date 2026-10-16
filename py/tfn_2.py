from fontTools.ttLib.ttFont import TTFont
import sys
from pathlib import Path
import regex as re
from dh import get_files, mpf, unique_path
from fontTools.ttLib import TTFont
from termcolor import cprint


def is_ascii_printable(s: str) -> bool:
    return all((32 <= ord(c) <= 126 for c in s))


def clean_filename(s: str) -> str:
    s = re.sub("[^\\w\\-\\.]", "", s)
    return s.strip("_-.")


def get_best_name(font: TTFont, name_id: int):
    fallback = None
    for rec in font["name"].names:
        if rec.nameID != name_id:
            continue
        try:
            name = rec.toUnicode().strip()
        except Exception:
            continue
        if rec.platformID == 3 and rec.langID == 1033:
            return name
        if is_ascii_printable(name):
            fallback = name
    return fallback


def get_font_names(path) -> tuple[str, str] | tuple[None, None] | None:
    font = TTFont(path)
    family = get_best_name(font, 1)
    subfamily = get_best_name(font, 2)
    if not family:
        return (None, None)
    family = clean_filename(family)
    subfamily = "Regular" if not subfamily else clean_filename(subfamily)
    if subfamily.lower() == family.lower():
        return (family, subfamily)


def process_file(fn: Path) -> int:
    try:
        family, style = get_font_names(fn)
    except Exception as e:
        cprint(f"error: {e}", "magenta")
        return 1
    if not family:
        cprint("name not found", "magenta")
        return 1
    ext = fn.suffix.lower()
    new_path = fn.parent / f"{family}-{style}{ext}"
    if fn.name == new_path.name:
        cprint("no change", "blue")
        return 0
    if new_path.exists():
        new_path = unique_path(new_path)
    fn.rename(new_path)
    print(f"{fn.name} -> ", end="")
    cprint(f"{new_path.name}", "green")
    return 0


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = [Path(arg) for arg in args] if args else get_files(cwd, ext=[".ttf", ".woff", ".woff2", ".bin", ".otf"])
    if not files:
        print("no files found")
        return
    if len(files) == 1:
        process_file(files[0])
        sys.exit(0)
    _ = mpf(process_file, files)


if __name__ == "__main__":
    main()
