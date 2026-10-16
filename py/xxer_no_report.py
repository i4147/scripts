from __future__ import annotations
import argparse
import gzip
import lzma
import os
import shutil
import tarfile
import tempfile
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from loguru import logger

try:
    import brotlicffi as brotli
except Exception:
    brotli = None
try:
    import py7zr
except Exception:
    py7zr = None
try:
    import zstandard as zstd
except Exception:
    zstd = None
SUPPORTED_EXTS = {
    ".tar.xz",
    ".tar.gz",
    ".tar.br",
    ".tar.zst",
    ".tar.7z",
    ".tar.zip",
    ".xz",
    ".gz",
    ".br",
    ".zst",
    ".7z",
    ".zip",
}


@dataclass
class Result:
    ok: bool
    src: str
    dst: Optional[str] = None
    error: Optional[str] = None


def has_compressed_suffix(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(ext) for ext in SUPPORTED_EXTS)


def output_name_for_file(path: Path, mode: str) -> Path:
    if mode == "xz":
        return path.with_name(path.name + ".xz")
    if mode == "gz":
        return path.with_name(path.name + ".gz")
    if mode == "brotli":
        return path.with_name(path.name + ".br")
    if mode == "zstd":
        return path.with_name(path.name + ".zst")
    if mode == "7z":
        return path.with_name(path.name + ".7z")
    if mode == "zip":
        return path.with_name(path.name + ".zip")
    raise ValueError(f"Unsupported mode: {mode}")


def output_name_for_dir(dir_path: Path, mode: str) -> Path:
    base = dir_path.name
    if mode == "xz":
        return dir_path.parent / f"{base}.tar.xz"
    if mode == "gz":
        return dir_path.parent / f"{base}.tar.gz"
    if mode == "brotli":
        return dir_path.parent / f"{base}.tar.br"
    if mode == "zstd":
        return dir_path.parent / f"{base}.tar.zst"
    if mode == "7z":
        return dir_path.parent / f"{base}.tar.7z"
    if mode == "zip":
        return dir_path.parent / f"{base}.tar.zip"
    raise ValueError(f"Unsupported mode: {mode}")


def atomic_write(src: Path, dst: Path, write_func, *args, **kwargsl):
    with tempfile.NamedTemporaryFile(delete=False, dir=dst.parent) as tmp:
        temp_path = Path(tmp.name)
        try:
            write_func(src, temp_path, *args, **kwargs)
            os.replace(temp_path, dst)
        except Exception as e:
            logger.exception(f"Atomic write failed for {dst}")
            temp_path.unlink(missing_ok=True)
            raise e


def tar_directory(src_dir: Path, tar_path: Path) -> None:
    with tarfile.open(tar_path, "w") as tf:
        tf.add(src_dir, arcname=src_dir.name)


def compress_file_xz(src: Path, dst: Path) -> None:
    with src.open("rb") as fin, lzma.open(dst, "wb", preset=9 | lzma.PRESET_EXTREME) as fout:
        shutil.copyfileobj(fin, fout)


def compress_file_gz(src: Path, dst: Path) -> None:
    with src.open("rb") as fin, gzip.open(dst, "wb", compresslevel=9) as fout:
        shutil.copyfileobj(fin, fout)


def compress_file_brotli(src: Path, dst: Path) -> None:
    if brotli is None:
        raise RuntimeError("brotlicffi is not installed")
    data = src.read_bytes()
    compressed = brotli.compress(data, quality=11)
    dst.write_bytes(compressed)


def compress_file_zstd(src: Path, dst: Path) -> None:
    if zstd is None:
        raise RuntimeError("zstandard is not installed")
    cctx = zstd.ZstdCompressor(level=22)
    with src.open("rb") as fin, dst.open("wb") as fout:
        with cctx.stream_writer(fout) as compressor:
            shutil.copyfileobj(fin, compressor)


def compress_file_zip(src: Path, dst: Path) -> None:
    with zipfile.ZipFile(dst, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.write(src, arcname=src.name)


def compress_file_7z(src: Path, dst: Path) -> None:
    if py7zr is None:
        raise RuntimeError("py7zr is not installed")
    with py7zr.SevenZipFile(dst, "w", filters=[{"id": py7zr.FILTER_LZMA2, "preset": 9}]) as zf:
        zf.write(src, arcname=src.name)


def compress_tar_with_7z(tar_src: Path, dst: Path) -> None:
    if py7zr is None:
        raise RuntimeError("py7zr is not installed")
    with py7zr.SevenZipFile(dst, "w", filters=[{"id": py7zr.FILTER_LZMA2, "preset": 9}]) as zf:
        zf.write(tar_src, arcname=tar_src.name)


def compress_tar_with_zip(tar_src: Path, dst: Path) -> None:
    with zipfile.ZipFile(dst, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.write(tar_src, arcname=tar_src.name)


def compress_tar_with_gz(tar_src: Path, dst: Path) -> None:
    with tar_src.open("rb") as fin, gzip.open(dst, "wb", compresslevel=9) as fout:
        shutil.copyfileobj(fin, fout)


def compress_tar_with_xz(tar_src: Path, dst: Path) -> None:
    with tar_src.open("rb") as fin, lzma.open(dst, "wb", preset=9 | lzma.PRESET_EXTREME) as fout:
        shutil.copyfileobj(fin, fout)


def compress_tar_with_brotli(tar_src: Path, dst: Path) -> None:
    if brotli is None:
        raise RuntimeError("brotlicffi is not installed")
    data = tar_src.read_bytes()
    dst.write_bytes(brotli.compress(data, quality=11))


def compress_tar_with_zstd(tar_src: Path, dst: Path) -> None:
    if zstd is None:
        raise RuntimeError("zstandard is not installed")
    cctx = zstd.ZstdCompressor(level=22)
    dst.write_bytes(cctx.compress(tar_src.read_bytes()))


def compress_one(path_str: str, mode: str, is_dir: bool) -> Result:
    src = Path(path_str)
    dst = None
    tar_path = None
    try:
        if is_dir:
            tar_path = src.parent / f"{src.name}.tar"
            tar_directory(src, tar_path)
            dst = output_name_for_dir(src, mode)
            if mode == "xz":
                atomic_write(tar_path, dst, compress_tar_with_xz)
            elif mode == "gz":
                atomic_write(tar_path, dst, compress_tar_with_gz)
            elif mode == "brotli":
                atomic_write(tar_path, dst, compress_tar_with_brotli)
            elif mode == "zstd":
                atomic_write(tar_path, dst, compress_tar_with_zstd)
            elif mode == "7z":
                atomic_write(tar_path, dst, compress_tar_with_7z)
            elif mode == "zip":
                atomic_write(tar_path, dst, compress_tar_with_zip)
            else:
                raise ValueError(f"Unsupported mode: {mode}")
            tar_path.unlink(missing_ok=True)
            src.rmdir()
            return Result(True, str(src), str(dst))
        else:
            dst = output_name_for_file(src, mode)
            if mode == "xz":
                atomic_write(src, dst, compress_file_xz)
            elif mode == "gz":
                atomic_write(src, dst, compress_file_gz)
            elif mode == "brotli":
                atomic_write(src, dst, compress_file_brotli)
            elif mode == "zstd":
                atomic_write(src, dst, compress_file_zstd)
            elif mode == "7z":
                atomic_write(src, dst, compress_file_7z)
            elif mode == "zip":
                atomic_write(src, dst, compress_file_zip)
            else:
                raise ValueError(f"Unsupported mode: {mode}")
            src.unlink()
            return Result(True, str(src), str(dst))
    except Exception as e:
        logger.exception(f"Failed to compress {src}")
        if tar_path and tar_path.exists():
            tar_path.unlink(missing_ok=True)
        if src.exists() and is_dir:
            pass
        elif src.exists() and not is_dir:
            pass
        return Result(False, str(src), error=str(e))


def decompress_one(path_str: str) -> Result:
    src = Path(path_str)
    extracted_path = None
    temp_file_to_remove = None
    try:
        name = src.name.lower()
        if name.endswith(".tar.xz"):
            extracted_path = src.parent / src.name[:-7]
            with tempfile.NamedTemporaryFile(delete=False, dir=src.parent) as tmp_tar:
                temp_file_to_remove = Path(tmp_tar.name)
                with lzma.open(src, "rb") as fin:
                    shutil.copyfileobj(fin, tmp_tar)
            with tarfile.open(temp_file_to_remove, "r:") as tf:
                tf.extractall(path=src.parent)
        elif name.endswith(".tar.gz"):
            extracted_path = src.parent / src.name[:-6]
            with tempfile.NamedTemporaryFile(delete=False, dir=src.parent) as tmp_tar:
                temp_file_to_remove = Path(tmp_tar.name)
                with gzip.open(src, "rb") as fin:
                    shutil.copyfileobj(fin, tmp_tar)
            with tarfile.open(temp_file_to_remove, "r:") as tf:
                tf.extractall(path=src.parent)
        elif name.endswith(".tar.br"):
            if brotli is None:
                raise RuntimeError("brotlicffi is not installed")
            extracted_path = src.parent / src.name[:-7]
            data = brotli.decompress(src.read_bytes())
            with tempfile.NamedTemporaryFile(delete=False, dir=src.parent) as tmp_tar:
                temp_file_to_remove = Path(tmp_tar.name)
                tmp_tar.write(data)
            with tarfile.open(temp_file_to_remove, "r:") as tf:
                tf.extractall(path=src.parent)
        elif name.endswith(".tar.zst"):
            if zstd is None:
                raise RuntimeError("zstandard is not installed")
            extracted_path = src.parent / src.name[:-8]
            dctx = zstd.ZstdDecompressor()
            with tempfile.NamedTemporaryFile(delete=False, dir=src.parent) as tmp_tar:
                temp_file_to_remove = Path(tmp_tar.name)
                with src.open("rb") as fin:
                    with dctx.stream_reader(fin) as reader:
                        shutil.copyfileobj(reader, tmp_tar)
            with tarfile.open(temp_file_to_remove, "r:") as tf:
                tf.extractall(path=src.parent)
        elif name.endswith(".tar.7z"):
            if py7zr is None:
                raise RuntimeError("py7zr is not installed")
            extracted_path = src.parent / src.name[:-7]
            with py7zr.SevenZipFile(src, "r") as zf:
                zf.extractall(path=src.parent)
        elif name.endswith(".tar.zip"):
            extracted_path = src.parent / src.name[:-8]
            with zipfile.ZipFile(src, "r") as zf:
                zf.extractall(path=src.parent)
        elif name.endswith(".xz"):
            extracted_path = src.with_suffix("")
            with lzma.open(src, "rb") as fin, extracted_path.open("wb") as fout:
                shutil.copyfileobj(fin, fout)
        elif name.endswith(".gz"):
            extracted_path = src.with_suffix("")
            with gzip.open(src, "rb") as fin, extracted_path.open("wb") as fout:
                shutil.copyfileobj(fin, fout)
        elif name.endswith(".br"):
            if brotli is None:
                raise RuntimeError("brotlicffi is not installed")
            extracted_path = src.with_suffix("")
            out_bytes = brotli.decompress(src.read_bytes())
            extracted_path.write_bytes(out_bytes)
        elif name.endswith(".zst"):
            if zstd is None:
                raise RuntimeError("zstandard is not installed")
            extracted_path = src.with_suffix("")
            dctx = zstd.ZstdDecompressor()
            with src.open("rb") as fin, extracted_path.open("wb") as fout:
                with dctx.stream_reader(fin) as reader:
                    shutil.copyfileobj(reader, fout)
        elif name.endswith(".7z"):
            if py7zr is None:
                raise RuntimeError("py7zr is not installed")
            extracted_path = src.with_suffix("")
            with py7zr.SevenZipFile(src, "r") as zf:
                zf.extractall(path=src.parent)
        elif name.endswith(".zip"):
            extracted_path = src.with_suffix("")
            with zipfile.ZipFile(src, "r") as zf:
                zf.extractall(path=src.parent)
        else:
            raise ValueError(f"Unsupported archive type: {src}")
        src.unlink()
        if temp_file_to_remove and temp_file_to_remove.exists():
            temp_file_to_remove.unlink()
        if extracted_path and extracted_path.exists():
            return Result(True, str(src), str(extracted_path))
        else:
            return Result(True, str(src))
    except Exception as e:
        logger.exception(f"Failed to decompress {src}")
        if temp_file_to_remove and temp_file_to_remove.exists():
            temp_file_to_remove.unlink()
        return Result(False, str(src), error=str(e))


def collect_top_level_items(base: Path):
    items = []
    for p in base.iterdir():
        if p.is_file():
            if not has_compressed_suffix(p):
                items.append((p, False))
        elif p.is_dir():
            if not has_compressed_suffix(p):
                items.append((p, True))
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description="Compress/decompress current directory recursively.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-c", "--compress", action="store_true", help="Compress")
    group.add_argument("-d", "--decompress", action="store_true", help="Decompress")
    parser.add_argument(
        "-f", "--file", action="store_true", help="Treat input as file mode (default for files, no effect for dirs)"
    )
    parser.add_argument("-7", "--7z", dest="use_7z", action="store_true", help="Use py7zr")
    parser.add_argument("-z", "--zstd", action="store_true", help="Use zstandard")
    parser.add_argument("-x", "--xz", action="store_true", help="Use xz")
    parser.add_argument("-g", "--gz", action="store_true", help="Use gzip")
    parser.add_argument("-b", "--brotli", action="store_true", help="Use brotlicffi")
    parser.add_argument("--zip", action="store_true", help="Use zipfile")
    args = parser.parse_args()
    if not args.compress and not args.decompress:
        args.compress = True
        args.xz = True
    if args.decompress:
        targets = []
        for p in Path(".").iterdir():
            if p.is_file() and has_compressed_suffix(p):
                targets.append(str(p))
        if not targets:
            print("No compressed files found to decompress.")
            return
        print(f"Found {len(targets)} compressed files. Starting decompression...")
        with ProcessPoolExecutor() as ex:
            futures = [ex.submit(decompress_one, t) for t in targets]
            for fut in as_completed(futures):
                res = fut.result()
                if res.ok:
                    print(f"Decompressed: {res.src} -> {res.dst if res.dst else 'N/A'}")
                else:
                    print(f"Failed to decompress: {res.src} - Error: {res.error}")
        return
    mode = "xz"
    if args.use_7z:
        mode = "7z"
    elif args.zstd:
        mode = "zstd"
    elif args.gz:
        mode = "gz"
    elif args.brotli:
        mode = "brotli"
    elif args.zip:
        mode = "zip"
    elif args.xz:
        mode = "xz"
    base = Path(".").resolve()
    items_to_process = collect_top_level_items(base)
    if not items_to_process:
        print("No files or directories to compress.")
        return
    print(f"Found {len(items_to_process)} items to compress using mode '{mode}'. Starting compression...")
    with ProcessPoolExecutor() as ex:
        futures = [ex.submit(compress_one, str(path), mode, is_dir) for path, is_dir in items_to_process]
        any_error = False
        results = []
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)
            if res.ok:
                print(f"Compressed: {res.src} -> {res.dst}")
            else:
                any_error = True
                print(f"Failed to compress: {res.src} - Error: {res.error}")
    if any_error:
        print("\nCompression finished with errors. Originals were preserved where errors occurred.")
    else:
        print("\nCompression finished successfully. Originals were removed.")


if __name__ == "__main__":
    main()
