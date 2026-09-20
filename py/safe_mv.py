import sys
from pathlib import Path
from shutil import move as _move


def unique_path(path: Path | str) -> Path:
    path = Path(path)
    if not path.exists():
        return path
    parent = path.parent
    suffixes = path.suffixes
    if suffixes:
        first_suffix_index = path.name.find(suffixes[0])
        stem = path.name[:first_suffix_index]
        full_suffix = "".join(suffixes)
    else:
        stem = path.name
        full_suffix = ""
    counter = 1
    while True:
        new_name = f"{stem}_{counter}{full_suffix}"
        new_path = parent / new_name
        if not new_path.exists():
            return new_path
        counter += 1


def safe_mv(
    src: str,
    dest: str,
    no_clobber=True,
) -> bool:
    src_path = Path(src)
    if not src_path.exists():
        print(
            f"Error: src '{src}' does not exist",
            file=sys.stderr,
        )
        return False
    dest_path = Path(dest)
    if dest_path.is_dir():
        dest_path /= src_path.name
    if no_clobber and dest_path.exists():
        dest_path = unique_path(dest_path)
    try:
        _move(str(src_path), str(dest_path))
        print(f"moved '{src}' -> '{dest_path}'")
        return True
    except Exception as e:
        print(
            f"Error moving file: {e}",
            file=sys.stderr,
        )
        return False


if __name__ == "__main__":
    infile = sys.argv[1]
    outfile = sys.argv[2]
    safe_mv(infile, outfile)
