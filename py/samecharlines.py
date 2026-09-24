import sys
from pathlib import Path


def is_repeated_char_line(line):
    stripped = line.rstrip("\n")
    if len(stripped) <= 1:
        return False
    return all(ch == stripped[0] for ch in stripped)


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <filename>")
        sys.exit(1)
    fname = sys.argv[1]
    if not Path(fname).is_file():
        print(f"Error: File '{fname}' not found.")
        sys.exit(1)
    with Path(fname).open(encoding="utf-8") as f:
        lines = f.readlines()
    filtered = [ln for ln in lines if not is_repeated_char_line(ln)]
    with Path(fname).open("w", encoding="utf-8") as f:
        f.writelines(filtered)


if __name__ == "__main__":
    raise SystemExit(main())
