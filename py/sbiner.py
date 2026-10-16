import shutil
from pathlib import Path


def main() -> None:
    current_dir = Path.cwd()
    sbin_dir = current_dir / "sbin"
    sbin_dir.mkdir(exist_ok=True)
    files_moved = 0
    for f in current_dir.iterdir():
        if f.is_file():
            try:
                if (Path("/system/bin") / f.name).exists():
                    shutil.move(str(f), sbin_dir / f.name)
                    print(f"Moved: {f.name} -> sbin/{f.name}")
                    files_moved += 1
            except Exception as e:
                print(f"Failed to move {f.name}: {e}")
    if files_moved == 0:
        print("No files moved. Make sure the files exist in current directory and match /system/bin names.")
    else:
        print(f"Total files moved: {files_moved}")


if __name__ == "__main__":
    main()
