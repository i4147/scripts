from pathlib import Path

EXCLUDED = {
    "tmp",
    "cache",
    "bin",
    "Android",
    ".git",
    "etc",
    "config",
    "var",
}
cwd = Path.cwd()
COUNT = 0
REMOVED_DIRS = []


def delete_empty_dirs(root: Path) -> None:
    global COUNT, REMOVED_DIRS
    for path in list(root.iterdir()):
        if path.is_dir():
            if path.name in EXCLUDED:
                continue
            if path.name.startswith("mc") and path.parent.name == "tmp":
                continue
            if any(pat in path.parts for pat in EXCLUDED):
                continue
            delete_empty_dirs(path)
            try:
                if not any(path.iterdir()):
                    path.rmdir()
                    COUNT += 1
                    REMOVED_DIRS.append(path.relative_to(cwd))
            except PermissionError:
                print(f"[ERR] {path.relative_to(cwd)}")
            except OSError as e:
                print(f"[ERROR] {path.relative_to(cwd)}: {e}")


if __name__ == "__main__":
    delete_empty_dirs(cwd)
    if COUNT:
        print("\nRemoved directories:")
        for d in REMOVED_DIRS:
            print(f"- {d}")
        print(f"count: {COUNT}")
    else:
        print("no empty dirs found.")
