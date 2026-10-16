import os
from pathlib import Path
from sys import exit
from dh import is_binary
from fastwalk import walk_files


def is_python_file(path: Path) -> bool:
    if is_binary(path):
        return False
    try:
        with Path(path).open(encoding="utf-8", errors="ignore") as f:
            first_lines = "".join(f.readlines(1024))
            if re.match("#!\\s*/.*python", first_lines):
                return True
            if "def " in first_lines or "class " in first_lines or "import " in first_lines:
                return True
    except:
        pass
    return False


def append_to_file(fpath: str, text: str) -> None:
    with Path(fpath).open("a", encoding="utf-8") as fo:
        fo.write("\n" + str(text) + "\n")


def process_file(fp: Path) -> bool | None:
    if not fp.exists():
        return False
    with Path(fp).open(encoding="utf-8") as f:
        first_line = f.readline()
        if first_line.startswith("#!/"):
            append_to_file("/sdcard/shebangs", first_line)
            print(first_line)
            return True
    return None


def main() -> None:
    dir = "/data/data/com.termux/files/home/bin"
    for pth in walk_files(dir):
        path = Path(os.path.join(dir, pth))
        if path.is_file() and path.suffix == ".py":
            process_file(path)
        if path.is_file() and (not path.suffix) and is_python_file(path):
            process_file(path)


if __name__ == "__main__":
    exit(main())
