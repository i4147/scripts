from pathlib import Path
import os
import pathlib
import re


def resolve_imports(content: str, current_dir: Path) -> str:
    folder_name = pathlib.Path(current_dir).name
    content = re.sub("from \\. import ([a-zA-Z0-9_]+)", f"from {folder_name} import \\1", content)
    content = re.sub("from \\.([a-zA-Z0-9_]+) import ([a-zA-Z0-9_]+)", f"from {folder_name}.\\1 import \\2", content)
    return re.sub("import \\.", f"import {folder_name}", content)


def merge_python_files() -> None:
    current_dir = pathlib.Path.cwd()
    folder_name = pathlib.Path(current_dir).name
    output_filename = f"{folder_name}.py"
    py_files = [f for f in os.listdir(current_dir) if f.endswith(".py") and f != output_filename]
    py_files.sort()
    with pathlib.Path(output_filename).open("w", encoding="utf-8") as outfile:
        for py_file in py_files:
            with pathlib.Path(py_file).open(encoding="utf-8") as infile:
                content = infile.read()
                content = resolve_imports(content, current_dir)
                outfile.write(f"\n\n# --- {py_file} ---\n\n")
                outfile.write(content)
    print(f"Merged {len(py_files)} files into {output_filename}")


if __name__ == "__main__":
    merge_python_files()
