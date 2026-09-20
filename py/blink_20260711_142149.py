import sys
from pathlib import Path

RM = -r in sys.argv


def get_files(directory: Path):
    for path in directory.rglob("*"):
        if ".git" in path.parts:
            continue
        if path.is_symlink():
            yield path


if __name__ == "__main__":
    cwd = Path.cwd()
    bcount = 0
    for path in get_files(cwd):
        if not path.exists():
            print(path.name)
            bcount += 1
            if RM:
                try:
                    path.unlink()
                    print(f"{path.relative_to(cwd)}")
                except Exception as e:
                    print(f"Error deleting {path}: {e}")
    if not RM and not bcount:
        print("no broken link found.")
        sys.exit(0)
    print(f"{bcount} broken link removed.")
