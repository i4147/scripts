import mmap
import sys
from pathlib import Path

import brotlicffi
from dh import cprint, fsz, get_files, gsz

CHUNK_SIZE = 32768
N_JOBS = -1


def decompress_chunk(data: bytes) -> bytes:
    return brotlicffi.decompress(data)


def parallel_decompress(in_path, out_path: Path) -> bool:
    try:
        file_size = in_path.stat().st_size
        if not file_size:
            return False
        with out_path.open("wb") as fout, in_path.open("rb") as fin:
            mm = mmap.mmap(fin.fileno(), length=0, access=mmap.ACCESS_READ)
            offset = 0
            while offset < file_size:
                block_size_bytes = mm[offset : offset + 4]
                if len(block_size_bytes) != 4:
                    break
                block_size = int.from_bytes(block_size_bytes, "big")
                offset += 4
                block_data_start = offset
                block_data_end = offset + block_size
                block_data = mm[block_data_start:block_data_end]
                decompressed_data = decompress_chunk(block_data)
                fout.write(decompressed_data)
                offset += block_size
            mm.close()
            return True
    except OSError:
        return False


def process_file(fp: Path) -> None:
    if not fp.stat().st_size:
        return
    if not fp.exists() or fp.suffix != ".br":
        return
    before = gsz(fp)
    outfile = Path(str(fp).replace(".br", ""))
    try:
        data = fp.read_bytes()
        decompressed_data = brotlicffi.decompress(data)
        outfile.write_bytes(decompressed_data)
        fp.unlink()
        return
    except:
        pass
    if parallel_decompress(fp, outfile):
        fp.unlink()
    elif outfile.exists():
        outfile.unlink()
        return
    after = gsz(outfile)
    ratio = round((after - before) / after * 100, 3)
    cprint(f"{outfile.name}", "green", end=" | ")
    cprint(f"{ratio}", "cyan")
    del before, after, ratio
    return


def main() -> None:
    root_dir = Path.cwd()
    before = gsz(root_dir)
    args = sys.argv[1:]
    files = [Path(arg) for arg in args] if args else get_files(root_dir)
    for f in files:
        process_file(f)
    diff_size = before - gsz(root_dir)
    print(f"{fsz(diff_size)}")


if __name__ == "__main__":
    sys.exit(main())
