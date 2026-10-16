import argparse
import bz2
import gzip
import lzma
import os
import shutil
import tarfile
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import brotlicffi as brotli
import psutil
import py7zr
import zstandard as zstd
from loguru import logger

COMPRESS_MODE = "zstd"
SUPPORTED_EXTS = {
    ".tar",
    ".tar.xz",
    ".tar.gz",
    ".tar.bz2",
    ".tar.br",
    ".tar.zst",
    ".tar.7z",
    ".xz",
    ".gz",
    ".bz2",
    ".br",
    ".zst",
    ".7z",
}


@dataclass
class Result:
    ok: bool
    src: str
    dst: Optional[str] = None
    error: Optional[str] = None
    original_size: int = 0
    new_size: int = 0


def get_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    elif path.is_dir():
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = Path(dirpath) / f
                total_size += fp.stat().st_size
        return total_size
    return 0


def format_size(size_bytes: int) -> str:
    if size_bytes is None:
        return "N/A"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024**2:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024**3:
        return f"{size_bytes / 1024**2:.2f} MB"
    else:
        return f"{size_bytes / 1024**3:.2f} GB"


def has_compressed_suffix(path: Path) -> bool:
    name = path.name.lower()
    return any((name.endswith(ext) for ext in SUPPORTED_EXTS))


def output_name_for_file(path: Path, mode: str) -> Path:
    if mode == "xz":
        return path.with_name(path.name + ".xz")
    if mode == "gz":
        return path.with_name(path.name + ".gz")
    if mode == "bz2":
        return path.with_name(path.name + ".bz2")
    if mode == "brotli":
        return path.with_name(path.name + ".br")
    if mode == "zstd":
        return path.with_name(path.name + ".zst")
    if mode == "7z":
        return path.with_name(path.name + ".7z")
    raise ValueError(f"Unsupported mode: {mode}")


def output_name_for_dir(dir_path: Path, mode: str) -> Path:
    base = dir_path.name
    if mode == "xz":
        return dir_path.parent / f"{base}.tar.xz"
    if mode == "gz":
        return dir_path.parent / f"{base}.tar.gz"
    if mode == "bz2":
        return dir_path.parent / f"{base}.tar.bz2"
    if mode == "brotli":
        return dir_path.parent / f"{base}.tar.br"
    if mode == "zstd":
        return dir_path.parent / f"{base}.tar.zst"
    if mode == "7z":
        return dir_path.parent / f"{base}.tar.7z"
    raise ValueError(f"Unsupported mode: {mode}")


def atomic_write(src: Path, dst: Path, write_func, *args, **kwargs) -> Path:
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, dir=dst.parent, prefix=f"{dst.stem}.") as tmp:
            temp_path = Path(tmp.name)
            write_func(src, temp_path, *args, **kwargs)
        os.replace(temp_path, dst)
        return dst
    except Exception as e:
        logger.exception(f"Atomic write failed for {dst}")
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise e


def tar_directory(src_dir: Path, tar_path: Path) -> None:
    with tarfile.open(tar_path, "w") as tf:
        tf.add(src_dir, arcname=src_dir.name)


def compress_file_gz(src: Path, dst: Path) -> None:
    with src.open("rb") as fin, gzip.open(dst, "wb", compresslevel=9) as fout:
        shutil.copyfileobj(fin, fout)


def compress_file_bz2(src: Path, dst: Path) -> None:
    with src.open("rb") as fin, bz2.open(dst, "wb", compresslevel=9) as fout:
        shutil.copyfileobj(fin, fout)


def compress_file_brotli(src: Path, dst: Path) -> None:
    if brotli is None:
        raise RuntimeError("brotlicffi is not installed")
    data = src.read_bytes()
    compressed = brotli.compress(data, quality=11)
    dst.write_bytes(compressed)


def compress_file_7z(src: Path, dst: Path) -> None:
    if py7zr is None:
        raise RuntimeError("py7zr is not installed")
    with py7zr.SevenZipFile(dst, "w", filters=[{"id": py7zr.FILTER_LZMA2, "preset": 9}]) as zf:
        zf.write(src, arcname=src.name)


def compress_file_xz(src: Path, dst: Path) -> None:
    with src.open("rb") as fin, lzma.open(dst, "wb", preset=9 | lzma.PRESET_EXTREME) as fout:
        shutil.copyfileobj(fin, fout)


def compress_one(path_str: str, mode: str, is_dir: bool) -> Result:
    src = Path(path_str)
    dst = None
    tar_path = None
    original_size = get_size(src)
    result = Result(ok=False, src=str(src), original_size=original_size)
    try:
        if is_dir:
            tar_path = src.parent / f"{src.name}.tar"
            tar_directory(src, tar_path)
            dst = output_name_for_dir(src, mode)
            atomic_write(
                tar_path,
                dst,
                {
                    "xz": compress_file_xz,
                    "gz": compress_file_gz,
                    "bz2": compress_file_bz2,
                    "brotli": compress_file_brotli,
                    "zstd": compress_file_zstd,
                    "7z": compress_file_7z,
                }[mode],
            )
            tar_path.unlink(missing_ok=True)
            shutil.rmtree(src)
            result.dst = str(dst)
            result.new_size = get_size(dst)
            result.ok = True
            return result
        else:
            dst = output_name_for_file(src, mode)
            atomic_write(
                src,
                dst,
                {
                    "xz": compress_file_xz,
                    "gz": compress_file_gz,
                    "bz2": compress_file_bz2,
                    "brotli": compress_file_brotli,
                    "zstd": compress_file_zstd,
                    "7z": compress_file_7z,
                }[mode],
            )
            src.unlink()
            result.dst = str(dst)
            result.new_size = get_size(dst)
            result.ok = True
            return result
    except Exception as e:
        logger.exception(f"Failed to compress {src}")
        result.error = str(e)
        if tar_path and tar_path.exists():
            tar_path.unlink(missing_ok=True)
        return result


def compress_file_zstd(src: Path, dst: Path) -> None:
    cctx = zstd.ZstdCompressor(level=9)
    with src.open("rb") as fin, dst.open("wb") as fout:
        cctx.copy_stream(fin, fout)


def decompress_zst_file(src: Path) -> Path:
    dctx = zstd.ZstdDecompressor()
    extracted_path = src.with_suffix("")
    with src.open("rb") as fin, extracted_path.open("wb") as fout:
        dctx.copy_stream(fin, fout)
    return extracted_path


def decompress_tar_zst(src: Path) -> Path:
    dst_dir = src.parent
    dctx = zstd.ZstdDecompressor()
    extracted_path = dst_dir / src.stem
    with src.open("rb") as fin:
        with dctx.stream_reader(fin) as reader:
            with tarfile.open(fileobj=reader, mode="r|*") as tf:
                tf.extractall(path=dst_dir, filter="data")
    return extracted_path


def mpf3(func, path_str: str):
    results = []
    max_workers = get_safe_workers
    print(f"max workers={max_workers}")
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(func, item): item for item in items}
        for future in as_completed(futures):
            results.append(future.result())
    return results


def get_safe_workers() -> int:
    total_mem = psutil.virtual_memory().total
    mem_headroom_gb = 2
    max_workers = max(1, (total_mem / 1024**3 - mem_headroom_gb) // 2)
    return int(max_workers)


def decompress_one(path_str: str) -> Result:
    src = Path(path_str)
    extracted_path_str: Optional[str] = None
    temp_file_to_remove: Optional[Path] = None
    original_size = get_size(src)
    result = Result(ok=False, src=str(src), original_size=original_size)
    try:
        name = src.name.lower()
        dst_dir = src.parent
        if name.endswith(".tar.xz"):
            extracted_path = dst_dir / src.stem
            with tempfile.NamedTemporaryFile(delete=False, dir=dst_dir, suffix=".tar") as tmp_tar:
                temp_file_to_remove = Path(tmp_tar.name)
                with lzma.open(src, "rb") as fin:
                    shutil.copyfileobj(fin, tmp_tar)
            with tarfile.open(temp_file_to_remove, "r:") as tf:
                tf.extractall(path=dst_dir, filter="data")
            extracted_path_str = str(extracted_path)
        elif name.endswith(".tar"):
            extracted_path = dst_dir / src.stem
            with tarfile.open(src, "r:") as tf:
                tf.extractall(path=dst_dir, filter="data")
            extracted_path_str = str(extracted_path)
        elif name.endswith(".tar.gz"):
            extracted_path = dst_dir / src.stem
            with tempfile.NamedTemporaryFile(delete=False, dir=dst_dir, suffix=".tar") as tmp_tar:
                temp_file_to_remove = Path(tmp_tar.name)
                with gzip.open(src, "rb") as fin:
                    shutil.copyfileobj(fin, tmp_tar)
            with tarfile.open(temp_file_to_remove, "r:") as tf:
                tf.extractall(path=dst_dir, filter="data")
            extracted_path_str = str(extracted_path)
        elif name.endswith(".tar.bz2"):
            extracted_path = dst_dir / src.stem
            with tempfile.NamedTemporaryFile(delete=False, dir=dst_dir, suffix=".tar") as tmp_tar:
                temp_file_to_remove = Path(tmp_tar.name)
                with bz2.open(src, "rb") as fin:
                    shutil.copyfileobj(fin, tmp_tar)
            with tarfile.open(temp_file_to_remove, "r:") as tf:
                tf.extractall(path=dst_dir, filter="data")
            extracted_path_str = str(extracted_path)
        elif name.endswith(".tar.br"):
            if brotli is None:
                raise RuntimeError("brotlicffi is not installed")
            extracted_path = dst_dir / src.stem
            data = brotli.decompress(src.read_bytes())
            with tempfile.NamedTemporaryFile(delete=False, dir=dst_dir, suffix=".tar") as tmp_tar:
                temp_file_to_remove = Path(tmp_tar.name)
                tmp_tar.write(data)
            with tarfile.open(temp_file_to_remove, "r:") as tf:
                tf.extractall(path=dst_dir, filter="data")
            extracted_path_str = str(extracted_path)
        elif name.endswith(".tar.7z"):
            if py7zr is None:
                raise RuntimeError("py7zr is not installed")
            extracted_path = dst_dir / src.stem
            with py7zr.SevenZipFile(src, "r") as zf:
                zf.extractall(path=dst_dir, filter="data")
            extracted_path_str = str(extracted_path)
        elif name.endswith(".xz"):
            extracted_path = src.with_suffix("")
            with lzma.open(src, "rb") as fin, extracted_path.open("wb") as fout:
                shutil.copyfileobj(fin, fout)
            extracted_path_str = str(extracted_path)
        elif name.endswith(".gz"):
            extracted_path = src.with_suffix("")
            with gzip.open(src, "rb") as fin, extracted_path.open("wb") as fout:
                shutil.copyfileobj(fin, fout)
            extracted_path_str = str(extracted_path)
        elif name.endswith(".bz2"):
            extracted_path = src.with_suffix("")
            with bz2.open(src, "rb") as fin, extracted_path.open("wb") as fout:
                shutil.copyfileobj(fin, fout)
            extracted_path_str = str(extracted_path)
        elif name.endswith(".br"):
            if brotli is None:
                raise RuntimeError("brotlicffi is not installed")
            extracted_path = src.with_suffix("")
            out_bytes = brotli.decompress(src.read_bytes())
            extracted_path.write_bytes(out_bytes)
            extracted_path_str = str(extracted_path)
        elif name.endswith(".zst"):
            extracted_path = src.with_suffix("")
            dctx = zstd.ZstdDecompressor()
            with src.open("rb") as fin, extracted_path.open("wb") as fout:
                dctx.copy_stream(fin, fout)
            extracted_path_str = str(extracted_path)
        elif name.endswith(".tar.zst"):
            extracted_path = dst_dir / src.stem
            dctx = zstd.ZstdDecompressor()
            with src.open("rb") as fin:
                with dctx.stream_reader(fin) as reader:
                    with tarfile.open(fileobj=reader, mode="r|*") as tf:
                        tf.extractall(path=dst_dir, filter="data")
            extracted_path_str = str(extracted_path)
        elif name.endswith(".7z"):
            if py7zr is None:
                raise RuntimeError("py7zr is not installed")
            extracted_name = src.stem
            extracted_path = dst_dir / extracted_name
            with py7zr.SevenZipFile(src, "r") as zf:
                zf.extractall(path=dst_dir)
            extracted_path_str = str(extracted_path)
        else:
            raise ValueError(f"Unsupported archive type: {src}")
        src.unlink()
        if temp_file_to_remove and temp_file_to_remove.exists():
            temp_file_to_remove.unlink()
        if extracted_path_str:
            result.dst = extracted_path_str
            result.new_size = get_size(Path(extracted_path_str))
            result.ok = True
        else:
            result.ok = True
        return result
    except Exception as e:
        logger.exception(f"Failed to decompress {src}")
        result.error = str(e)
        if temp_file_to_remove and temp_file_to_remove.exists():
            temp_file_to_remove.unlink()
        return result


def collect_items(base: Path) -> list[Tuple[Path, bool]]:
    items = []
    for p in base.iterdir():
        if p.is_file():
            if not has_compressed_suffix(p):
                items.append((p, False))
        elif p.is_dir():
            if not has_compressed_suffix(p) and (not p.name == ".git"):
                items.append((p, True))
    return items


def main() -> None:
    global COMPRESS_MODE
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
    parser.add_argument("--bz2", action="store_true", help="Use bz2")
    args = parser.parse_args()
    if not args.compress and (not args.decompress):
        args.compress = True
        args.zstd = True
    overall_original_size = 0
    overall_new_size = 0
    processed_count = 0
    error_count = 0
    if args.decompress:
        targets = []
        for p in Path(".").iterdir():
            if p.is_file() and has_compressed_suffix(p):
                targets.append(str(p))
        if not targets:
            print("No compressed files found to decompress.")
            return
        print(f"Found {len(targets)} compressed files. Starting decompression...")
        results = mpf3(decompress_one, targets)
        for res in results:
            processed_count += 1
            if res.ok:
                print(
                    f"Decompressed: {res.src} -> {(res.dst if res.dst else 'N/A')} | Size: {format_size(res.original_size)} -> {format_size(res.new_size)}"
                )
                overall_original_size += res.original_size
                overall_new_size += res.new_size
            else:
                error_count += 1
                print(f"Failed to decompress: {res.src} - Error: {res.error}")
    else:
        mode = "zstd"
        if args.use_7z:
            mode = "7z"
        elif args.zstd:
            mode = "zstd"
        elif args.gz:
            mode = "gz"
        elif args.brotli:
            mode = "brotli"
        elif args.bz2:
            mode = "bz2"
        elif args.xz:
            mode = "xz"
        base = Path.cwd()
        items_to_process = collect_items(base)
        if not items_to_process:
            print("No files or directories to compress.")
            return
        print(f"Found {len(items_to_process)} items to compress using mode '{mode}'. Starting compression...")
        COMPRESS_MODE = mode
        results = []
        for f in items_to_process:
            path, is_dir = f
            results.append(compress_one(path_str=str(path), mode=COMPRESS_MODE, is_dir=is_dir))
        for res in results:
            processed_count += 1
            if res.ok:
                print(
                    f"Compressed: {res.src} -> {res.dst} | Size: {format_size(res.original_size)} -> {format_size(res.new_size)}"
                )
                overall_original_size += res.original_size
                overall_new_size += res.new_size
            else:
                error_count += 1
                print(f"Failed to compress: {res.src} - Error: {res.error}")
    if processed_count == 0:
        print("No items were processed.")
        return
    if error_count > 0:
        print(f"Completed with {error_count} error(s).")
    if overall_original_size > 0:
        reduction = overall_original_size - overall_new_size
        percent_reduction = reduction / overall_original_size * 100 if overall_original_size > 0 else 0
        print(f"Total original size: {format_size(overall_original_size)}")
        print(f"Total new size:      {format_size(overall_new_size)}")
        print(f"Total size reduction: {format_size(abs(reduction))} ({percent_reduction:.2f}%)")
    else:
        print("Could not determine overall size changes.")


if __name__ == "__main__":
    main()
