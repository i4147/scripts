from pathlib import Path
import os
import pathlib

TARGET_SHEBANG = "#!/data/data/com.termux/files/usr/bin/python"


def is_python_file(filepath) -> bool:
    if pathlib.Path(filepath).stat().st_size == 0 or filepath.endswith("__init__.py"):
        return False
    if filepath.endswith(".py"):
        return True
    try:
        with pathlib.Path(filepath).open(encoding="utf-8") as f:
            first_line = f.readline().strip()
            if first_line.startswith("#!") and "python" in first_line:
                return True
            if first_line.startswith("#") and (
                "python" in first_line or "encoding" in first_line or "noqa" in first_line
            ):
                return True
            f.seek(0)
            for line in f:
                line = line.strip()
                if line and (not line.startswith("#")):
                    return line.startswith(("import ", "from "))
            return False
    except (OSError, UnicodeDecodeError):
        return False


def process_file(filepath) -> None:
    with pathlib.Path(filepath).open("r+", encoding="utf-8") as f:
        lines = f.readlines()
        if not lines:
            return
        if lines and lines[0].startswith("#!"):
            lines[0] = TARGET_SHEBANG + "\n"
            if len(lines) > 1 and lines[1].strip() != "":
                lines.insert(1, "\n")
        else:
            has_python_code = any((line.strip().startswith(("import ", "from ", "def ", "class ")) for line in lines))
            if has_python_code:
                lines.insert(0, TARGET_SHEBANG + "\n")
                lines.insert(1, "\n")
        f.seek(0)
        f.writelines(lines)
        f.truncate()
    if "bin" in filepath.split(os.sep):
        pathlib.Path(filepath).chmod(493)


def traverse_directory(directory: Path) -> None:
    for root, _, files in os.walk(directory):
        for filename in files:
            filepath = os.path.join(root, filename)
            if is_python_file(filepath):
                process_file(filepath)


if __name__ == "__main__":
    traverse_directory(pathlib.Path.cwd())
