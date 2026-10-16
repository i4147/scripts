import pathlib
from multiprocessing import Pool
from sys import exit
from time import perf_counter

from rignore import walk

txt_file = pathlib.Path("/sdcard/txt").open(encoding="utf-8")
EXT = [line.strip() for line in txt_file if line.strip()]
txt_file.close()


def process_file(fp) -> bool:
    doit = False
    if fp.exists() and not fp.is_symlink():
        with pathlib.Path(fp).open(encoding="utf-8") as f:
            lines = f.readlines()
            if len(lines) < 5:
                doit = True
    if doit:
        pass

        pathlib.Path(fp).unlink()
        print(f"{fp.name} removed")
        return True
    return False


def main() -> None:
    start = perf_counter()
    files = []
    for path in walk("."):
        if path.is_dir() or path.is_symlink():
            continue
        if path.is_file() and path.suffix[1:] in EXT:
            files.append(path)
    pool = Pool(12)
    for f in files:
        _ = pool.apply_async(process_file, ((f),))
    pool.close()
    pool.join()
    print(f"{perf_counter() - start} sec")


if __name__ == "__main__":
    exit(main())
