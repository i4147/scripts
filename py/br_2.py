import mmap
import sys
from pathlib import Path

from binaryornot import is_binary
from brotlicffi import compress as brotli_compress
from dh import cprint, fsz, get_files, gsz, mpf3

CHUNK_SIZE = 524288
N_JOBS = -1


def compress_in_memory(infile, outfile, mode: int) -> bool:
    try:
        data = infile.read_bytes()
        compressed_data = brotli_compress(data, mode=mode, quality=11)

        outfile.write_bytes(compressed_data)
        return True
    except Exception:
        return False
    finally:
        try:
            del data
        except:
            pass
        try:
            del compressed_data
        except:
            pass


def compress_chunk(data: bytes, mode: int = 0):
    return brotli_compress(data, mode=mode, quality=11)


def parallel_compress(in_path, out_path: Path) -> bool:
    try:
        mode = 0 if is_binary(in_path) else 1

        file_size = in_path.stat().st_size
        if not file_size:
            return False

        if file_size < CHUNK_SIZE:
            return compress_in_memory(in_path, out_path, mode)

        chunk_count = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE

        with out_path.open("wb", buffering=1024 * 1024) as fout:
            with in_path.open("rb") as fin:
                with mmap.mmap(fin.fileno(), length=0, access=mmap.ACCESS_READ) as mm:
                    for i in range(chunk_count):
                        start = i * CHUNK_SIZE
                        end = min(start + CHUNK_SIZE, file_size)

                        chunk = mm[start:end]

                        block = compress_chunk(chunk, mode)
                        fout.write(len(block).to_bytes(4, "big"))
                        fout.write(block)

                        del chunk, block

        return True

    except OSError:
        return False


def process_file(fp) -> None:
    if not fp.exists() or fp.suffix == ".br":
        return

    before = gsz(fp)
    if not before:
        return

    outfile = Path(str(fp) + ".br")

    try:
        if parallel_compress(fp, outfile):
            fp.unlink()
        elif outfile.exists():
            outfile.unlink()

        after = gsz(outfile) if outfile.exists() else 0
        dsz = abs(before - after)
        ratio = dsz / before * 100 if before > 0 else 0

        cprint(f"{outfile.name}", "green", end=" | ")
        cprint(f"{fsz(dsz)} | {ratio:.2f}%", "cyan")

    finally:
        del before, after, dsz, ratio


def main() -> int:
    cwd = Path.cwd()
    before = gsz(cwd)

    args = sys.argv[1:]
    files = [Path(arg) for arg in args] if args else get_files(cwd)

    mpf3(process_file, files)

    diff_size = before - gsz(cwd)
    print(f"{fsz(diff_size)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
