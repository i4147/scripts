import sys
from pathlib import Path

RM = "-r" in sys.argv


def get_files(directory: Path):
    for path in directory.rglob("*"):
        if ".git" in path.parts:
            continue
        if path.is_symlink():
            yield path


if __name__ == "__main__":
    cwd = Path.cwd()
    bcount = 0
    broken_links = []

    for path in get_files(cwd):
        if not path.exists():
            print(path.name)
            bcount += 1
            broken_links.append(str(path.relative_to(cwd)))
            if RM:
                try:
                    path.unlink()
                    print(f"Removed: {path.relative_to(cwd)}")
                except Exception as e:
                    print(f"Error deleting {path}: {e}")

    if broken_links:
        blink_file = cwd / "blink.txt"
        with open(blink_file, "w") as f:
            for link in broken_links:
                f.write(f"{link}\n")
        print(f"\nBroken links saved to: {blink_file}")

    if not RM and not bcount:
        print("no broken link found.")
        sys.exit(0)

    action = "removed" if RM else "found"
    print(f"{bcount} broken link {action}.")
