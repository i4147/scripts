import shutil
import sys
from pathlib import Path


def main() -> None:
    cwd = Path("/data/data/com.termux/files/usr")
    nl = []
    for f in cwd.rglob("licenses"):
        if f.is_dir():
            if "dist-info" in str(f.parent):
                print(f)
                ans = input()
                if ans == "n":
                    sys.exit(0)
                shutil.rmtree(f)


if __name__ == "__main__":
    sys.exit(main())
