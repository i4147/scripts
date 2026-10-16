from multiprocessing import Pool
from pathlib import Path
from sys import exit

from dh import folder_size, format_size
from fastwalk import walk_files


def process_file(fp) -> bool:
    if not fp.exists():
        return False
    print(f"{fp} : {fp.suffix}")
    return True


def main() -> None:
    dir = Path().cwd()
    start_size = folder_size(dir)
    files = []
    for pth in walk_files(dir):
        path = Path(pth)
        if path.is_file():
            files.append(path)
    pool = Pool(8)
    for _k in pool.imap_unordered(process_file, files):
        pass
    pool.close()
    pool.join()
    end_size = folder_size(dir)
    print(f"{format_size(abs(end_size - start_size))}")


if __name__ == "__main__":
    exit(main())
