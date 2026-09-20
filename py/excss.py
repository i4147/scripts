from bs4.element import PageElement
import os
import random
import string
from pathlib import Path
from sys import exit
from time import perf_counter

from bs4 import BeautifulSoup
from fastwalk import walk_files
from termcolor import cprint


def save_style(str1: list[PageElement]) -> bool:
    fn = "css/"
    if not Path("css").exists():
        Path("css").mkdir()
    for _i in range(10):
        fn += random.choice(string.ascii_lowercase)
    fn += ".css"
    if Path(fn).exists():
        cprint(f"[{fn}] exists.", "red")
        return False
    if not Path(fn).exists():
        Path(fn).write_text("\n".join(list(str1)), encoding="utf-8")
        cprint(f"{[fn]} created.", "cyan")
    return True


def save_script(str1) -> bool:
    fn = "js/"
    if not Path("js").exists():
        Path("js").mkdir()
    for _i in range(10):
        fn += random.choice(string.ascii_lowercase)
    fn += ".js"
    if Path(fn).exists():
        cprint(f"[{fn}] exists.", "red")
        return False
    if not Path(fn).exists():
        Path(fn).write_text("\n".join(list(str1)), encoding="utf-8")
        cprint(f"{[fn]} created.", "cyan")
    return True


def process_file(fp: Path) -> bool:
    html_content = Path(fp).read_text(encoding="utf-8")
    soup = BeautifulSoup(html_content, "html.parser")
    styles = soup.find_all("style")
    scripts = soup.findall("script")
    if styles:
        cprint(
            f"{[fp.name]} : {len(styles)} styles found.",
            "magenta",
        )
        for style in styles:
            save_style(style.contents)
    if scripts:
        cprint(
            f"{[fp.name]} : {len(scripts)} scripts found.",
            "magenta",
        )
        for script in scripts:
            save_script(script.contents)
    return True


def main() -> None:
    start = perf_counter()
    dir = Path.cwd()
    for pth in walk_files(dir):
        path = Path(os.path.join(dir, pth))
        if path.is_file() and path.suffix == ".html":
            process_file(path)
    print(f"{perf_counter() - start} sec")


if __name__ == "__main__":
    exit(main())
