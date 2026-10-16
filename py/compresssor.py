from __future__ import annotations
import argparse
import gzip
import lzma
import shutil
import tarfile
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
    try:
        if is_dir:
            tar_path = src.parent / f"{src.name}.tar"
            tar_directory(src, tar_path)
            dst = output_name_for_dir(src, mode)
            if mode == "xz":
                compress_tar_with_xz(tar_path, dst)
            elif mode == "gz":
                compress_tar_with_gz(tar_path, dst)
            elif mode == "brotli":
                compress_tar_with_brotli(tar_path, dst)
            elif mode == "zstd":
                compress_tar_with_zstd(tar_path, dst)
            elif mode == "7z":
                compress_tar_with_7z(tar_path, dst)
            elif mode == "zip":
                compress_tar_with_zip(tar_path, dst)
            else:
                raise ValueError(f"Unsupported mode: {mode}")
            tar_path.unlink(missing_ok=True)
            src.rmdir()
            return Result(True, str(src), str(dst))
        else:
            dst = output_name_for_file(src, mode)
            if mode == "xz":
                compress_file_xz(src, dst)
            elif mode == "gz":
                compress_file_gz(src, dst)
            elif mode == "brotli":
                compress_file_brotli(src, dst)
            elif mode == "zstd":
                compress_file_zstd(src, dst)
            elif mode == "7z":
                compress_file_7z(src, dst)
            elif mode == "zip":
                compress_file_zip(src, dst)
            else:
                raise ValueError(f"Unsupported mode: {mode}")
            src.unlink()
            return Result(True, str(src), str(dst))
    except Exception as e:
        logger.exception(f"Failed to compress {src}")
        return Result(False, str(src), error=str(e))


def decompress_one(path_str: str) -> Result:
    src = Path(path_str)
    try:
        name = src.name.lower()
        if name.endswith(".tar.xz"):
            out = src.with_suffix("").with_suffix("")
            with lzma.open(src, "rb") as fin, tarfile.open(fileobj=fin, mode="r:") as tf:
                tf.extractall(path=src.parent)
            src.unlink()
            extracted = src.parent / src.name[:-7]
            if extracted.is_dir():
                return Result(True, str(src), str(extracted))
        elif name.endswith(".tar.gz"):
            with gzip.open(src, "rb") as fin, tarfile.open(fileobj=fin, mode="r:") as tf:
                tf.extractall(path=src.parent)
            src.unlink()
        elif name.endswith(".tar.br"):
            if brotli is None:
                raise RuntimeError("brotlicffi is not installed")
            data = brotli.decompress(src.read_bytes())
            tmp_tar = src.with_suffix("")
            tmp_tar.write_bytes(data)
            with tarfile.open(tmp_tar, "r:") as tf:
                tf.extractall(path=src.parent)
            tmp_tar.unlink()
            src.unlink()
        elif name.endswith(".tar.zst"):
            if zstd is None:
                raise RuntimeError("zstandard is not installed")
            dctx = zstd.ZstdDecompressor()
            tmp_tar = src.with_suffix("")
            with src.open("rb") as fin, tmp_tar.open("wb") as fout:
                dctx.copy_stream(fin, fout)
            with tarfile.open(tmp_tar, "r:") as tf:
                tf.extractall(path=src.parent)
            tmp_tar.unlink()
            src.unlink()
        elif name.endswith(".tar.7z"):
            if py7zr is None:
                raise RuntimeError("py7zr is not installed")
            with py7zr.SevenZipFile(src, "r") as zf:
                zf.extractall(path=src.parent)
            src.unlink()
        elif name.endswith(".tar.zip"):
            with zipfile.ZipFile(src, "r") as zf:
                zf.extractall(path=src.parent)
            src.unlink()
        elif name.endswith(".xz"):
            out = src.with_suffix("")
            with lzma.open(src, "rb") as fin, out.open("wb") as fout:
                shutil.copyfileobj(fin, fout)
            src.unlink()
        elif name.endswith(".gz"):
            out = src.with_suffix("")
            with gzip.open(src, "rb") as fin, out.open("wb") as fout:
                shutil.copyfileobj(fin, fout)
            src.unlink()
        elif name.endswith(".br"):
            if brotli is None:
                raise RuntimeError("brotlicffi is not installed")
            out = src.with_suffix("")
            out.write_bytes(brotli.decompress(src.read_bytes()))
            src.unlink()
        elif name.endswith(".zst"):
            if zstd is None:
                raise RuntimeError("zstandard is not installed")
            out = src.with_suffix("")
            dctx = zstd.ZstdDecompressor()
            with src.open("rb") as fin, out.open("wb") as fout:
                dctx.copy_stream(fin, fout)
            src.unlink()
        elif name.endswith(".7z"):
            if py7zr is None:
                raise RuntimeError("py7zr is not installed")
            with py7zr.SevenZipFile(src, "r") as zf:
                zf.extractall(path=src.parent)
            src.unlink()
        elif name.endswith(".zip"):
            with zipfile.ZipFile(src, "r") as zf:
                zf.extractall(path=src.parent)
            src.unlink()
        else:
            raise ValueError(f"Unsupported archive type: {src}")
        return Result(True, str(src))
    except Exception as e:
        logger.exception(f"Failed to decompress {src}")
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
    parser.add_argument("-f", "--file", action="store_true", help="Treat input as file mode")
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
            print("No compressed files found.")
            return
        with ProcessPoolExecutor() as ex:
            futures = [ex.submit(decompress_one, t) for t in targets]
            for fut in as_completed(futures):
                res = fut.result()
                if res.ok:
                    print(f"Decompressed: {res.src}")
                else:
                    print(f"Failed: {res.src} -> {res.error}")
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
    items = collect_top_level_items(base)
    if not items:
        print("No files or directories to compress.")
        return
    with ProcessPoolExecutor() as ex:
        futures = [ex.submit(compress_one, str(path), mode, is_dir) for path, is_dir in items]
        any_error = False
        results = []
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)
            if res.ok:
                print(f"Compressed: {res.src} -> {res.dst}")
            else:
                any_error = True
                print(f"Failed: {res.src} -> {res.error}")
    if any_error:
        print("Some items failed; originals were preserved where errors occurred.")


if __name__ == "__main__":
    main()
