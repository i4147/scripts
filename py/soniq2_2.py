import mmap
import sys
import tempfile
from multiprocessing import Pool
from pathlib import Path
from typing import Final
from loguru import logger

MB_5 = 5 * 1024 * 1024
POOL_SIZE = 8


def _strip_line(line):
    return line.strip()


def sort_and_uniq(path):
    path = Path(path)
    if not path.exists():
        logger.error("File '{}' not found.", path)
        return
    try:
        size = path.stat().st_size
        if size > MB_5:
            with (
                path.open("r+b") as f,
                mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm,
            ):
                lines = mm.read().decode("utf-8").splitlines()
        else:
            lines = path.read_text(encoding="utf-8").splitlines()
        with Pool(processes=POOL_SIZE) as pool:
            async_results = [pool.apply_async(_strip_line, (line,)) for line in lines]
            processed_lines = [res.get() for res in async_results]
        unique_sorted_lines = sorted(set(processed_lines))
        fd, temp_path_str = tempfile.mkstemp(dir=path.parent)
        temp_path = Path(temp_path_str)
        try:
            with open(fd, "w", encoding="utf-8") as tmp:
                tmp.writelines(line + "\n" for line in unique_sorted_lines)
            temp_path.replace(path)
            print("Successfully updated '{}'.", path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
    except Exception as e:
        logger.error("Failed to process file: {}", e)


def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py <filename>")
        return
    sort_and_uniq(sys.argv[1])


if __name__ == "__main__":
    main()
