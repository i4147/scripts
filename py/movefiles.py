import argparse
import shutil
from pathlib import Path


def move_files(list_file: Path, dest_root: Path) -> None:
    dest_root = dest_root.resolve()
    moved = 0
    missing = 0
    with list_file.open("r", encoding="utf-8") as f:
        for line in f:
            rel = line.strip()
            if not rel or rel.startswith("#"):
                continue
            src = Path(rel)
            if not src.exists():
                print(f"Missing: {src}")
                missing += 1
                continue
            dest = dest_root / src
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            print(f"Moved: {src} -> {dest}")
            moved += 1
    print(f"\nDone. moved={moved}, missing={missing}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("filelist", help="Text file containing relative paths")
    ap.add_argument("destination", help="Destination directory")
    args = ap.parse_args()
    move_files(Path(args.filelist), Path(args.destination))


if __name__ == "__main__":
    main()
