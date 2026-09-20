import operator
import os
import pathlib
import stat
import sys

CYAN = "\033[36m"
BLUE = "\033[34m"
GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"
COMPRESSED_EXTS = {
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".rar",
    ".7z",
}


def human_readable_size(size_bytes) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024**2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024**3:
        return f"{size_bytes / 1024**2:.1f} MB"
    else:
        return f"{size_bytes / 1024**3:.1f} GB"


def get_dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda e: None):
        for f in files:
            try:
                fp = os.path.join(root, f)
                if pathlib.Path(fp).is_file():
                    total += pathlib.Path(fp).stat().st_size
            except Exception:
                pass
    return total


def list_dir(path: str = ".") -> None:
    try:
        entries = os.listdir(path)
    except Exception as e:
        print(f"Error accessing {path}: {e}")
        return
    items = []
    for entry in entries:
        full_path = os.path.join(path, entry)
        try:
            if pathlib.Path(full_path).is_dir():
                size = get_dir_size(full_path)
                color = BLUE
            else:
                size = pathlib.Path(full_path).stat().st_size
                mode = os.stat(full_path).st_mode
                ext = os.path.splitext(entry)[1].lower()
                if ext in COMPRESSED_EXTS:
                    color = RED
                elif mode & stat.S_IXUSR:
                    color = GREEN
                else:
                    color = CYAN
        except Exception:
            size = 0
            color = CYAN
        items.append((size, entry, color))
    size_col_width = max(
        (len(human_readable_size(s)) for s, _, _ in items),
        default=4,
    )
    name_col_width = max((len(n) for _, n, _ in items), default=4)
    print(f"{'size'.ljust(size_col_width)}  {'name'}")
    print("-" * (size_col_width + name_col_width + 2))
    if not items:
        print("(directory is empty)")
        return
    for size, name, color in sorted(items, key=operator.itemgetter(0)):
        size_str = human_readable_size(size).ljust(size_col_width)
        print(f"{size_str}  {color}{name}{RESET}")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    list_dir(target)
