import shutil
import sys
from pathlib import Path

EMPTYIT = "-e" in sys.argv
RMIT = "-r" in sys.argv
SKIP_DIRS = ["lazy", ".git"]


def empty_it(path: Path) -> None:
    path.write_text("", encoding="utf-8")


def remove_it(fp: Path) -> None:
    if fp.exists():
        if fp.is_dir():
            shutil.rmtree(fp)
        else:
            fp.unlink()


def main() -> None:
    cwd = Path.cwd()
    junk_files = {
        "license",
        "license.rst",
        "license.md",
        "license.txt",
        "license.mit",
        "author",
        "authors",
        "authors.md",
    }
    junkset = set([p.strip() for p in junk_files])
    c = 0
    for path in cwd.rglob("*"):
        if ".git" in path.parts or "lazy" in path.parts or "var" in path.parts:
            continue
        loname = path.name.lower()
        if loname in junkset:
            print(f"{path.name} removed.")
            remove_it(path)
            continue
        if loname in {
            "copying",
            "license",
            "license.md",
            "license.txt",
            "license.rst",
            "license.mit",
            "author",
            "contributing",
        }:
            path.unlink()
            print(f"{path.name} removed.")
            continue
        if path.is_file() and loname.endswith((".tmp", ".bak", ".log", ".pyc")):
            remove_it(path)
            print(path.relative_to(cwd))
            c += 1
            continue
        if path.is_file() and loname in {
            ".travis.yml",
            "third_party_notices",
            ".gitkeep",
            ".dirinfo",
            ".pyformat_cache.json",
            "simz.json",
            "copyright",
        }:
            path.unlink()
            print(path.relative_to(cwd))
            c += 1
            continue
        if path.is_file() and loname.endswith("license.txt") or loname == "license":
            path.unlink()
            c += 1
            print(path.relative_to(cwd))
            continue
        if any(p in loname for p in junkset):
            if RMIT:
                path.unlink()
                print(path.relative_to(cwd))
                c += 1
                continue
            else:
                empty_it(path)
                print(path.relative_to(cwd))
                c += 1
        if path.is_dir() and path.name == "licenses" and "dist-info" in path.parent.name:
            remove_it(path)
            print(path.relative_to(cwd))
            c += 1
    if c:
        print(f"{c} item removed")


if __name__ == "__main__":
    sys.exit(main())
