from __future__ import annotations

import sys
from pathlib import Path

inplace = "-i" in sys.argv


def fold_file(path: Path, width=35) -> None:
    if inplace:
        new_path = path
    else:
        new_path = path.with_name(path.stem + "_folded" + path.suffix)
    content = path.read_text(encoding="utf-8", errors="ignore")
    lines = content.splitlines()
    folded_lines = []
    for line in lines:
        while len(line) > width:
            folded_lines.append(line[:width])
            line = line[width:]
        if line:
            folded_lines.append(line)
    with new_path.open("w", encoding="utf-8") as fo:
        for line in folded_lines:
            fo.write(line + "\n")
    print(f"{new_path.name} created")


if __name__ == "__main__":
    path = Path(sys.argv[1])
    fold_file(path)
