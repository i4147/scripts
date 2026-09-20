import os
import pathlib
import shutil


def main() -> None:
    dir2 = "/data/data/com.termux/files/home/isaac/venv/lib/python3.12/site-packages"
    dir1 = "/data/data/com.termux/files/usr/lib/python3.12/site-packages"
    sp1dirs = [p for p in os.listdir(dir1) if pathlib.Path(os.path.join(dir1, p)).is_dir()]
    sp2dirs = [p for p in os.listdir(dir2) if pathlib.Path(os.path.join(dir2, p)).is_dir()]
    sp1files = [p for p in os.listdir(dir1) if pathlib.Path(os.path.join(dir1, p)).is_file()]
    sp2files = [p for p in os.listdir(dir2) if pathlib.Path(os.path.join(dir2, p)).is_file()]
    [p for p in sp1dirs if p not in sp2dirs]
    dirs_only_in_venv = [p for p in sp2dirs if p not in sp1dirs]
    common_dirs = [p for p in sp1dirs if p in sp2dirs]
    common_files = [p for p in sp1files if p in sp2files]
    [p for p in sp1files if p not in sp2files]
    files_only_in_venv = [p for p in sp2files if p not in sp1files]
    for k in common_files:
        full_path = os.path.join(dir2, k)
        print(f"removing {full_path}")
        pathlib.Path(full_path).unlink()
    for x in common_dirs:
        full_path = os.path.join(dir2, x)
        print(f"removing {full_path}")
        shutil.rmtree(full_path)
    for z in dirs_only_in_venv:
        full_path = os.path.join(dir2, z)
        print(f"moving {full_path} to spkg")
        dest = os.path.join(dir1, z)
        shutil.move(full_path, dest)
    for t in files_only_in_venv:
        full_path = os.path.join(dir2, t)
        print(f"moving {full_path} to spkg")
        dest = os.path.join(dir1, t)
        shutil.move(full_path, dest)


if __name__ == "__main__":
    main()
