

import sys
import tarfile
from pathlib import Path

import zstandard as zstd
from dh import cprint, fsz, get_files, gsz


def decompress_file(archive_path: Path) -> bool:
    try:
        dctx = zstd.ZstdDecompressor()
        extracted_path = archive_path.with_suffix("")
        with archive_path.open("rb") as fin, extracted_path.open("wb") as fout:
            dctx.copy_stream(fin, fout)
        archive_path.unlink()
        return True
    except:
        print(f"{archive_path} : decompress failed")
        return False


def decompress_tar_zst(archive_path: Path) -> bool:
    try:
        dst_dir = archive_path.parent
        dctx = zstd.ZstdDecompressor()
        extracted_path = dst_dir / archive_path.stem
        with archive_path.open("rb") as fin:
            with dctx.stream_reader(fin) as reader:
                with tarfile.open(fileobj=reader, mode="r|*") as tf:
                    tf.extractall(path=dst_dir, filter="data")
        archive_path.unlink()
        return True
    except:
        print(f"{archive_path} : decompress failed")
        return False


def main() -> None:
    sys.argv[1:]
    cwd = Path.cwd()
    before = gsz(cwd)
    files = get_files(cwd, ext=[".zst", ".tar.zst"])
    if not files:
        print("No files to compress")
        return
    successful = 0
    failed = 0
    total_files = len(files)
    for i, path in enumerate(sorted(files), 1):
        print(f"\n[{i}/{total_files}] {path.name}")
        if path.name.endswith(".tar.zst"):
            if decompress_tar_zst(path):
                successful += 1
            else:
                failed += 1
        if path.name.endswith(".zst"):
            if decompress_file(path):
                successful += 1
            else:
                failed += 1
    print(f"successful: {successful}")
    if failed:
        print(f"failed: {failed}")
    after = gsz(cwd)
    dsz = abs(before - after)
    ratio = dsz / before * 100
    cprint(f"space change: {fsz(dsz)} | {ratio:.2f}%")


if __name__ == "__main__":
    sys.exit(main())
