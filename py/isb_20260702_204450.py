from pathlib import Path

from binaryornot import is_binary
from dh import cprint, get_filez, read_lines


def main() -> None:
    nl = set()
    cwd = Path("/data/data/com.termux")
    lines = read_lines("bext", ke=False)
    for path in get_filez(cwd):
        c = 0
        for ext in lines:
            ext = ext.strip().lower()
            if path.suffix.lower() == ext:
                c += 1
                if not is_binary(path):
                    if path.suffix not in nl:
                        nl.add(path.suffix)
                        cprint(ext)
        if not c:
            print(f"no file with extension {ext} found.")

    if not nl:
        print(f"no file with ext  {lines} found")
    nl = list(nl)
    with open("surely_text", "a") as f:
        f.write("\n")
        for k in nl:
            f.write(f"{k}\n")


if __name__ == "__main__":
    main()
