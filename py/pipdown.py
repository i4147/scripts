from subprocess import CompletedProcess
import multiprocessing as mp
import subprocess
import sys
from time import perf_counter


def process_pkg(pk) -> CompletedProcess[bytes]:
    return subprocess.run(
        ["pip", "download", "--no-deps", pk],
        check=False,
    )


def main() -> None:
    start = perf_counter()
    with open("js.txt") as f:
        lines = [l.strip() for l in f.readlines()]
    pool = mp.Pool(8)
    for line in lines:
        _ = pool.apply_async(process_pkg, ((line),))
    pool.close()
    pool.join()
    print(f"{perf_counter() - start} sec")


if __name__ == "__main__":
    sys.exit(main())
