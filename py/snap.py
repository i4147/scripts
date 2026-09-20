import mmap
import sys
from pathlib import Path

import brotlicffi
from multiprocessing import Pool
from collections import deque
from dh import fsz, get_files, gsz, rss
from joblib import Parallel, delayed

CHUNK_SIZE = 1048576
QUALITY = 11
N_JOBS = -1


def compress_chunk(data: bytes, quality=QUALITY):
    return brotlicffi.compress(data, quality=quality)


def parallel_compress(in_path: Path, out_path: Path) -> None:
    file_size = in_path.stat().st_size
    chunk_count = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE
    with out_path.open("wb", buffering=1024 * 1024) as fout, in_path.open("rb") as fin:
        mm = mmap.mmap(fin.fileno(), length=0, access=mmap.ACCESS_READ)
        chunks = [mm[i * CHUNK_SIZE : min((i + 1) * CHUNK_SIZE, file_size)] for i in range(chunk_count)]
        compressed_chunks = Parallel(n_jobs=N_JOBS, backend="loky")(
            (delayed(compress_chunk)(chunk) for chunk in chunks)
        )
        for block in compressed_chunks:
            fout.write(len(block).to_bytes(4, "big"))
            fout.write(block)
        mm.close()


def process_file(path) -> None:
    path = Path(path)
    if not path.exists() or path.suffix == ".br":
        return
    before = gsz(path)
    br_path = path.with_name(path.name + ".br")

    parallel_compress(path, br_path)

    path.unlink()
    after = gsz(outfile)
    rss(path, before, after)
    del before, after
    return


def main() -> None:
    cwd = Path.cwd()
    before = gsz(cwd)
    args = sys.argv[1:]
    files = [Path(arg) for arg in args] if args else get_files(cwd)
    pool = Pool(8)
    for f in files:
        p = deque()
        p.append(pool.apply_async(process_file, (f,)))
        if len(p) > 8:
            p.popleft().get()
    while p:
        p.popleft().get()
    pool.close()
    pool.join()
    diff_size = before - gsz(cwd)
    print(f"{fsz(diff_size)}")


if __name__ == "__main__":
    sys.exit(main())
