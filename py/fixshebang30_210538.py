import sys
from pathlib import Path

major, minor, _, _, _ = sys.version_info
py_version = f"{major}{minor}"
OLD = {
    "#!/data/data/com.termux/files/usr/bin/env python3",
    "#!/data/data/com.termux/files/usr/bin/python3",
    "#!/data/data/com.termux/files/usr/bin/python3.13",
    "#!/data/data/com.termux/files/usr/bin/python3.12",
    "#!/data/data/com.termux/files/usr/bin/python2",
    "#!/data/data/com.termux/files/usr/bin/python2.7",
    "#!/data/data/com.termux/files/usr/bin/python#!/usr/bin/env python",
    "#!/usr/bin/env python3",
}
NEW = "#!/data/data/com.termux/files/usr/bin/env python\n"


def fix_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines(keepends=False)
    if not lines:
        return False
    nl = []
    if not lines[0].startswith("#!"):
        nl.append(NEW)
        nl.extend(lines)
        path.write_text("\n".join(nl) + "\n", encoding="utf-8")
        return True
    if any((lines[0] == p for p in OLD)):
        lines[0] = NEW
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True
    return False


def main() -> None:
    fixed = 0
    cwd = Path.cwd()
    for file in cwd.rglob("*.py"):
        if fix_file(file):
            fixed += 1
            print(f"Updated: {file}")
    print(f"\nDone. Updated {fixed} files.")


if __name__ == "__main__":
    main()
