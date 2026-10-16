import os
import pathlib
import shutil


def sync_top_level_dirs_and_files(dir1: str, dir2: str) -> None:
    items1 = set(os.listdir(dir1))
    items2 = set(os.listdir(dir2))
    dirs1 = {i for i in items1 if pathlib.Path(os.path.join(dir1, i)).is_dir()}
    files1 = items1 - dirs1
    dirs2 = {i for i in items2 if pathlib.Path(os.path.join(dir2, i)).is_dir()}
    files2 = items2 - dirs2
    common_dirs = dirs1 & dirs2
    dirs_only_in_1 = dirs1 - dirs2
    for d in common_dirs:
        path = os.path.join(dir1, d)
        print(f"Removing common directory from first: {path}")
        shutil.rmtree(path)
    for d in dirs_only_in_1:
        src = os.path.join(dir1, d)
        dst = os.path.join(dir2, d)
        print(f"Moving directory {src} → {dst}")
        shutil.move(src, dst)
    common_files = files1 & files2
    files_only_in_1 = files1 - files2
    for f in common_files:
        path = os.path.join(dir1, f)
        print(f"Removing common file from first: {path}")
    for f in files_only_in_1:
        src = os.path.join(dir1, f)
        dst = os.path.join(dir2, f)
        print(f"Moving file {src} → {dst}")
    print("Done.")


dir1 = "/data/data/com.termux/files/home/isaac/venv/lib/python3.12/site-packages"
dir2 = "/data/data/com.termux/files/usr/lib/python3.12/site-packages"
sync_top_level_dirs_and_files(dir1, dir2)
