from pathlib import Path
from sys import exit

from dh import TXT_EXT, cprint, get_filez


def process_file(fp: Path) -> None:
    outfile = "/sdcard/b64"
    c = 0
    try:
        lines = fp.read_text(encoding="utf-8").splitlines(keepends=True)
        with open(outfile, "a") as fo:
            for line in lines:
                if "base64," in line:
                    fo.write(f"\n{line}")
                    c += 1
            if c:
                cprint(f"{fp.name} : {c}")
    except:
        return


def main() -> None:
    cwd = Path("/sdcard/_static")
    for path in get_filez(cwd):
        if path.is_file() and path.suffix in TXT_EXT:
            process_file(path)


if __name__ == "__main__":
    exit(main())
