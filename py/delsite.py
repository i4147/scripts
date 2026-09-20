import os
from sys import exit


def main() -> None:
    dir1 = "/data/data/com.termux/files/home/venv/lib/python3.12/site-packages"
    dir2 = "/data/data/com.termux/files/usr/lib/python3.12/site-packages"
    files1 = os.listdir(dir1)
    files2 = os.listdir(dir2)
    for f in files1:
        if f in files2:
            path = f"bin/{f}"
            if os.path.isdir(path):
                print(f)
            if os.path.isfile(path):
                print(f)


if __name__ == "__main__":
    exit(main())
