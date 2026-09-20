import shutil
from pathlib import Path


def main() -> None:
    current_dir = Path.cwd()
    efl_dir = current_dir / "efl"
    efl_dir.mkdir(exist_ok=True)
    files_moved = 0
    for f in current_dir.iterdir():
        if f.is_file() and "efl" in f.name.lower():
            try:
                shutil.move(str(f), efl_dir / f.name)
                print(f"Moved: {f.name} -> efl/{f.name}")
                files_moved += 1
            except Exception as e:
                print(f"Failed to move {f.name}: {e}")
    if files_moved == 0:
        print("No efl binary files found to move.")
    else:
        print(f"Total files moved: {files_moved}")


if __name__ == "__main__":
    main()
