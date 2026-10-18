import sys
from pathlib import Path


def main() -> None:
    cwd = Path.cwd()
    req = sys.argv[1].strip()
    found = [path for path in cwd.glob("*") if req in path.name and (not path.is_symlink())]
    for k in sorted(found):
        print(f"  - {k.name}")


if __name__ == "__main__":
    main()
