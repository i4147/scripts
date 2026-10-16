import os
import string
from pathlib import Path

import rignore
from fontTools.ttLib import TTFont

FONT_SUFFIX = [
    ".ttf",
    ".otf",
    ".eot",
    ".woff",
    ".woff2",
]


def get_font_name(file_path: Path):
    try:
        font = TTFont(file_path)
        for record in font["name"].names:
            if record.nameID == 1:
                try:
                    return record.string.decode("utf-8").strip()
                except UnicodeDecodeError:
                    try:
                        return record.string.decode("utf-16-be").strip()
                    except UnicodeDecodeError:
                        try:
                            return record.string.decode("gb2312").strip()
                        except UnicodeDecodeError:
                            return record.string.decode("latin-1").strip()
    except Exception as e:
        return f"Error: {e}"


def normalize_name(aname: str):
    ln = len(aname)
    if aname.endswith("woff"):
        sfx = aname[ln - 5 :]
        aname = aname[0 : ln - 5]
    elif aname.endswith("woff2"):
        sfx = aname[ln - 6 :]
        aname = aname[0 : ln - 6]
    else:
        sfx = aname[ln - 4 :]
        aname = aname[0 : ln - 4]
    cleaned = ""
    for ch in aname:
        if ch == " ":
            cleaned += "_"
            continue
        if ch in string.punctuation:
            cleaned += "-"
            continue
        if ch in string.printable:
            cleaned += ch
        else:
            cleaned += "-"
    cleaned += sfx
    return cleaned


def main() -> None:
    for pth in rignore.walk("."):
        path = Path(pth)
        if path.suffix in FONT_SUFFIX:
            fname = get_font_name(path)
            print(f"{path.name}  :  {fname}")
            new_path = os.path.join(
                path.parent,
                fname + "." + path.suffix,
            )
            if str(new_path) != str(path):
                if "error" in str(new_path).lower():
                    continue
                new_path = normalize_name(str(new_path))
                if not Path(new_path).exists():
                    Path(path).rename(new_path)
                    print(f"{path.name} renamed to   --> {Path(new_path).name}")
                else:
                    print("file exists")
            else:
                print("already renamed.")


if __name__ == "__main__":
    main()
