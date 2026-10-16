from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import nbformat


def is_import_line(line):
    return line.startswith(("import ", "from "))


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


def nb2py(notebook):
    imports = []
    os_mods = []
    sys_mods = []
    main_code = []
    for cell in notebook.cells:
        if cell.cell_type == "markdown":
            md_text = cell.source.replace("\n", "\n# ")
            main_code.append(f"# {md_text}\n")
        elif cell.cell_type == "code":
            cell_code = cell.source
            lines = cell_code.split("\n")
            for line in lines:
                if line.strip().startswith("!nb2py"):
                    continue
                if is_import_line(line):
                    imports.append(line)
                    continue
                if line.startswith("os.environ"):
                    os_mods.append(line)
                    continue
                if line.startswith("sys.path"):
                    sys_mods.append(line)
                    continue
                cleaned = strip_magics(line)
                main_code.append(cleaned)
    for i, line in enumerate(imports):
        if "import os" in line or "from os import" in line:
            for mod in sorted(os_mods, reverse=True):
                imports.insert(i + 1, mod)
            break
    for i, line in enumerate(imports):
        if "import sys" in line or "from sys import" in line:
            for mod in sorted(sys_mods, reverse=True):
                imports.insert(i + 1, mod)
            break
    imports_str = "\n".join(imports) + "\n\n"
    main_str = "\n".join(main_code)
    indent = "    "
    main_indented = "\n".join(f"{indent}{ln}" for ln in main_str.split("\n"))
    return f"{imports_str}if __name__ == '__main__':\n{main_indented}"


def process_file(path):
    path = Path(path)
    fo = path.with_suffix(".py")
    if fo.exists():
        return None
    with path.open(encoding="utf-8") as f:
        nb = nbformat.read(f, as_version=4)
    py_code = nb2py(nb)
    with fo.open("w", encoding="utf-8") as out:
        out.write(py_code)
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
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(process_file, f) for f in files]
        for future in as_completed(futures):
            result = future.result()
            if result:
                print(result)
