import sys
from pathlib import Path

from fastwalk import walk_files


def main() -> None:
    ext1 = input("ext 1 :")
    ext2 = input("ext 2 :")
    choice = input("remove which one: 1 or 2")
    if choice == "1":
        todel = ext1
    else:
        todel = ext2
    for pth in walk_files("."):
        path = Path(pth)
        if path.is_file() and path.suffix == ext1:
            twin = path.with_suffix(ext2)
            if twin.exists() and twin.suffix == todel:
                print("( [✔] {path.name} , [✖]{twin.name})")
                twin.unlink()
            else:
                print("( [✔] {twin.name} , [✖]{path.name})")
                path.unlink()


if __name__ == "__main__":
    sys.exit(main())
