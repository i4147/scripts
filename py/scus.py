import os
import pathlib
import sys


def setup_zipped_pkgs() -> None:
    python_path = "/data/data/com.termux/files/usr/lib/python3.12"
    zip_dir = os.path.join(python_path, "site-packages")
    if not pathlib.Path(zip_dir).is_dir():
        return
    if zip_dir not in sys.path:
        sys.path.insert(0, zip_dir)
    for item in os.listdir(zip_dir):
        item_path = os.path.join(zip_dir, item)
        if (item.endswith((".zip", "_libs"))) and item_path not in sys.path:
            sys.path.insert(0, item_path)


setup_zipped_pkgs()
