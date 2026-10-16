import os
import pathlib
import sys


def setup_zipped_loader() -> None:
    prefix = "/data/data/com.termux/files/usr/lib/python3.12"
    zip_dir = os.path.join(prefix, "zipped-pkgs")
    if not pathlib.Path(zip_dir).exists():
        return
    if zip_dir not in sys.path:
        sys.path.insert(0, zip_dir)
    for item in os.listdir(zip_dir):
        if item.endswith("_libs"):
            lib_path = os.path.join(zip_dir, item)
            if lib_path not in sys.path:
                sys.path.insert(0, lib_path)


if "com.termux" in os.environ.get("PREFIX", ""):
    setup_zipped_loader()
