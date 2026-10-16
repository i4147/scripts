import os
import pathlib
import re


def refactor_file(file_path: str) -> None:
    content = pathlib.Path(file_path).read_text(encoding="utf-8")
    content = re.sub(
        r"os\.path\.join\(([^,]+),\s*([^)]+)\)",
        r"(pathlib.Path(\g<1>) / \g<2>)",
        content,
    )
    content = re.sub(
        r"os\.listdir\(([^)]+)\)",
        r"[f.name for f in pathlib.Path(\g<1>).iterdir()]",
        content,
    )
    content = re.sub(r"os\.remove\(([^)]+)\)", r"pathlib.Path(\g<1>).unlink()", content)
    if "import os" in content:
        content = content.replace("import os", "import os\\nimport pathlib")
    pathlib.Path(file_path).write_text(content, encoding="utf-8")


for root, _dirs, files in os.walk("."):
    for file in files:
        if file.endswith(".py"):
            print(f"Processing {os.path.join(root, file)}")
            refactor_file(os.path.join(root, file))
