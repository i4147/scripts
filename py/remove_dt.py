from pathlib import Path
import re


pattern = re.compile(r"_\d{8}_\d{6}(?=\.[^.]+$)")

for path in Path(".").rglob("*"):
    if not path.is_file():
        continue

    new_name = pattern.sub("", path.name)

    if new_name != path.name:
        new_path = path.with_name(new_name)
        print(f"Renaming: {path} -> {new_path}")
        path.rename(new_path)
