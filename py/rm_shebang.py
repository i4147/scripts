from pathlib import Path
import os
import pathlib

TARGET_SHEBANG = "#!/data/data/com.termux/files/usr/bin/python"


def is_python_file(filepath) -> bool | None:
    if pathlib.Path(filepath).stat().st_size == 0 or filepath.endswith("__init__.py"):
        return False
    if filepath.endswith(".py"):
        return True
    return None


def remove_shebang(filepath) -> bool:
    s1 = "#!/data/data/com.termux/files/usr/bin/python\n"
    s2 = "#!/data/data/com.termux/files/usr/bin/python3\n"
    s3 = "#!/data/data/com.termux/files/usr/bin/env python\n"
    s4 = "#!/data/data/com.termux/files/usr/bin/env python3\n"
    s5 = "#!/usr/bin/env python\n"
    s6 = "#!/usr/bin/env python3\n"
    cleaned = []
    with pathlib.Path(filepath).open(encoding="utf-8") as f:
        lines = f.readlines()
        first_line = lines[0]
        if first_line in {s1, s2, s3, s4, s5, s6}:
            for line in lines[1:]:
                cleaned.append(line)
        else:
            return False
    with pathlib.Path(filepath).open("w", encoding="utf-8") as fo:
        fo.writelines(cleaned)
    return True


def traverse_directory(directory: Path) -> None:
    cat1 = []
    for root, _, files in os.walk(directory):
        for filename in files:
            filepath = os.path.join(root, filename)
            if is_python_file(filepath):
                if remove_shebang(filepath):
                    pass
                else:
                    cat1.append(filepath)
    for _x in cat1:
        pass
    with pathlib.Path("noshebang").open("w", encoding="utf-8") as fg:
        fg.writelines((str(k) + "\n" for k in cat1))


if __name__ == "__main__":
    traverse_directory(pathlib.Path.cwd())
