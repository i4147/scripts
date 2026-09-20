from __future__ import annotations

import sys
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

import nbformat


def strip_magics(source: str) -> str:
    lines = source.split("\n")
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()

        if stripped.startswith(("%", "!", "%%")):
            result.append(f"# [MAGIC] {line.rstrip()}")

            while i < len(lines) - 1 and line.rstrip().endswith("\\"):
                i += 1
                line = lines[i]
                result.append(f"# [MAGIC] {line.rstrip()}")
        else:
            result.append(line)

        i += 1

    return "\n".join(result)


def process_file(path):
    path = Path(path)
    fo = path.with_suffix(".py")

    if fo.exists():
        return None

    with path.open(encoding="utf-8") as f:
        nb = nbformat.read(f, as_version=4)

    lines = ["#!/usr/bin/env python3\n"]
    for i, cell in enumerate(nb.cells, 1):
        lines.append(f"#[{i}] ({cell.cell_type})\n")

        if cell.cell_type == "markdown":
            for line in cell.source.splitlines():
                lines.append(f"# {line}\n")
            lines.append("\n")

        elif cell.cell_type == "code":
            cleaned = strip_magics(cell.source)
            lines.append(cleaned)
            lines.append("\n\n")

    with fo.open("w", encoding="utf-8") as out:
        out.writelines(lines)

    return f"Exported → {fo.name}"


if __name__ == "__main__":
    cwd = Path.cwd()
    args = sys.argv[1:]

    if args:
        files = []
        for arg in args:
            p = Path(arg)
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                files.extend(p.rglob("*.ipynb"))
    else:
        files = list(cwd.rglob("*.ipynb"))

    with ProcessPoolExecutor() as executor:
        futures = [executor.submit(process_file, f) for f in files]
        for future in as_completed(futures):
            result = future.result()
            if result:
                print(result)
