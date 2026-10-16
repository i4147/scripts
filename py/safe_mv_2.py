import shutil
import sys
from pathlib import Path

from loguru import logger


def get_unique_filename(dest: Path) -> Path:
    if not dest.exists():
        return dest
    parent = dest.parent
    name = dest.name
    if "." in name:
        stem, ext = name.rsplit(".", 1)
        ext = "." + ext
    else:
        stem, ext = name, ""
    counter = 1
    while True:
        new_name = f"{stem}_{counter}{ext}"
        new_path = parent / new_name
        if not new_path.exists():
            return new_path
        counter += 1


def safe_mv(src: str, dest: str, verbose: bool = False) -> bool:
    src_path = Path(src)
    if not src_path.exists():
        msg = f"Source '{src}' does not exist."
        raise FileNotFoundError(msg)
    dest_path = Path(dest)
    if dest_path.exists() and dest_path.is_dir():
        dest_path /= src_path.name
    dest_path = get_unique_filename(dest_path)
    try:
        Path(src_path).rename(dest_path)
        if verbose:
            logger.info(f"Renamed '{src}' -> '{dest_path}'")
        return True
    except OSError:
        try:
            shutil.copy2(src_path, dest_path)
            Path(src_path).unlink()
            if verbose:
                logger.info(f"Copied+Deleted '{src}' -> '{dest_path}'")
            return True
        except Exception as e:
            logger.info(f"Failed to move file: {e}")
            return False


if __name__ == "__main__":
    safe_mv(sys.argv[1], sys.argv[2])
