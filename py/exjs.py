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


def save_script(str1: list[PageElement], fpath) -> bool:
    if not Path("js").exists():
        Path("js").mkdir()
    fn = f"js/{fpath.stem[:8].replace(' ', '_')}_"
    for _i in range(10):
        fn += random.choice(string.ascii_lowercase)
    fn += ".js"
    if Path(fn).exists():
        cprint(f"[{fn}] exists.", "red")
        return False
    if not Path(fn).exists():
        fl = str(str1[:50])
        fl = fl.replace(" ", "")
        if fl.lstrip().startswith("{"):
            fn += "on"
            Path(fn).write_text("\n".join(list(str1)), encoding="utf-8")
            cprint(f"{[fn]} created.", "green")
        else:
            Path(fn).write_text("\n".join(list(str1)), encoding="utf-8")
            cprint(f"{[fn]} created.", "cyan")
    return True


def process_file(fp: Path) -> bool:
    html_content = Path(fp).read_text(encoding="utf-8")
    soup = BeautifulSoup(html_content, "html.parser")
    scripts = soup.find_all("script")
    if scripts:
        cprint(
            f"{[fp.name]} : {len(scripts)} scripts found.",
            "magenta",
        )
        for script in scripts:
            save_script(script.contents, fp)
    return True


def main() -> None:
    dir = "/sdcard/Download"
    start = perf_counter()
    for pth in walk_files(dir):
        path = Path(os.path.join(dir, pth))
        if path.is_file() and (path.suffix in {".html", ".htm"}):
            process_file(path)
    print(f"{perf_counter() - start} sec")


if __name__ == "__main__":
    exit(main())
