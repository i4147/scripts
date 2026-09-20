import shutil
import sysconfig
from pathlib import Path

from dh import format_size
from fastwalk import walk_dirs, walk_files
from termcolor import cprint


def get_skip_dirs():
    skip = set()
    site_packages = Path(sysconfig.get_paths()["purelib"])
    skip.update(
        str(site_packages / d)
        for d in (
            "regex",
            "pip",
            "wheel",
            "setuptools",
        )
    )
    return skip


def clean_pyc_and_pycache(
    start_dir: Path = Path.cwd(),
) -> None:
    total_size = 0
    dirs_removed = 0
    files_removed = 0
    d2r = []
    skip_dirs = get_skip_dirs()
    for pth in walk_files(start_dir):
        path = Path(pth)
        if path.is_file() and any(pat in path.parts for pat in skip_dirs):
            continue
        if path.is_file() and path.suffix == ".pyc":
            try:
                if path.parent.name != "__pycache__":
                    twin_path = path.with_suffix(".py")
                else:
                    parent_dir = path.parent.parent
                    if ".cpython-312" in path.stem:
                        twin_path = Path(str(parent_dir) + "/" + str(path.stem).replace(".cpython-312", "") + ".py")
                    if ".cpython-313" in path.stem:
                        twin_path = Path(str(parent_dir) + "/" + str(path.stem).replace(".cpython-313", "") + ".py")
                    if ".opt-1" in path.stem:
                        twin_path = Path(str(parent_dir) + "/" + str(path.stem).replace(".opt-1", "") + ".py")
                    if ".opt-2" in path.stem:
                        twin_path = Path(str(parent_dir) + "/" + str(path.stem).replace(".opt-2", "") + ".py")
                if twin_path.exists():
                    size = path.stat().st_size
                    path.unlink()
                    total_size += size
                    files_removed += 1
                else:
                    cprint(twin_path, "green")
                    cprint(f"{path} : lonely pyc", "cyan")
            except Exception as e:
                print(f"⚠️ error deleting {path}: {e}")
    for dirp in walk_dirs(start_dir):
        path = Path(dirp)
        if path.is_dir() and path.name == "__pycache__":
            d2r.append(path)
        if path.is_dir() and ".git" in path.parts:
            continue
        if path.is_dir() and any(str(path).startswith(sd) for sd in skip_dirs):
            continue
    for d in d2r:
        if d.exists():
            try:
                shutil.rmtree(d)
                dirs_removed += 1
            except Exception as e:
                print(f"⚠️ Could not delete {path}: {e}")
    print(f"   • .pyc files removed: {files_removed}")
    print(f"   • Total size freed: {format_size(total_size)}")
    print(f"   • __pycache__ directories removed: {dirs_removed}")


if __name__ == "__main__":
    clean_pyc_and_pycache()
