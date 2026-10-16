import os
import shutil
import sys
from pathlib import Path

from loguru import logger


def cprint(text: str, color: str = "cyan") -> None:
    colors = {
        "black": 30,
        "red": 91,
        "green": 92,
        "yellow": 93,
        "blue": 94,
        "magenta": 95,
        "cyan": 96,
        "white": 97,
        "gray": 90,
        "default": 39,
    }
    color_code = colors.get(color.lower(), 39)
    print(f"\033[5;{color_code}m{text}\033[0m")


def fsz(sz: float) -> str:
    sz = abs(int(sz))
    units = ("", "K", "M", "G", "T")
    if sz == 0:
        return "0 B"
    i = min(int(int(sz).bit_length() - 1) // 10, len(units) - 1)
    sz /= 1024**i
    return f"{sz:.2f} {units[i]}B"


def get_filez(root_dir: Path, ext: str):
    if not root_dir.is_dir() or not root_dir.exists():
        return []
    for r, _, files in os.walk(root_dir):
        for f in files:
            fullpath = Path(r) / f
            if fullpath.is_symlink():
                continue
            if fullpath.is_file() and fullpath.suffix == ext:
                yield fullpath


def clean_pyc_and_pycache() -> None:
    major, minor, _, _, _ = sys.version_info
    cwd = Path.cwd()
    total_size = 0
    dirs_removed = 0
    files_removed = 0
    for path in get_filez(cwd, ext=".pyc"):
        pyfile_samedir = path.with_name(
            path.name
            .replace(f".cpython-{major}{minor}", "")
            .replace(".opt-1", "")
            .replace(".opt-2", "")
            .replace("-pytest-9.0.2", "")
        ).with_suffix(".py")
        pyfile_parentdir = path.parent.parent / pyfile_samedir.name
        if not pyfile_samedir.exists() and not pyfile_parentdir.exists():
            cprint(
                f"{pyfile_samedir} {pyfile_parentdir} does not exists so {path.name} is lonely pyc",
                "cyan",
            )
            continue
        if pyfile_parentdir.exists() or pyfile_samedir.exists():
            sz = path.stat().st_size
            path.unlink()
            total_size += sz
            files_removed += 1
    d2r = [dirp for dirp in cwd.rglob("__pycache__") if dirp.is_dir()]
    for d in d2r:
        if d.exists():
            try:
                d.rmdir()
                dirs_removed += 1
            except Exception:
                try:
                    shutil.rmtree(str(d))
                    dits_temoved += 1
                except:
                    logger.info(f"ertor removing {d}")
    if not files_removed and not dirs_removed:
        logger.info("nothing found")
        sys.exit(0)
    logger.info(f"files removed: {files_removed}")
    logger.info(f"dirs  removed: {dirs_removed}")
    logger.info(f"Total size: {fsz(total_size)}")


if __name__ == "__main__":
    clean_pyc_and_pycache()
