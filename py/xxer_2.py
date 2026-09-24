from lzma import LZMAFile
from gzip import GzipFile
from bz2 import BZ2File
from _io import TextIOWrapper
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
from typing import Optional, Tuple, List


try:
    import brotlicffi as brotli
except ImportError:
    try:
        import brotli
    except ImportError:
        brotli = None

try:
    import psutil
except ImportError:
    psutil = None

try:
    import py7zr
except ImportError:
    py7zr = None

try:
    import zstandard as zstd
except ImportError:
    zstd = None

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
COMPRESSION_LEVELS = {"xz": 9, "gz": 9, "bz2": 9, "brotli": 11, "zstd": 9, "7z": 9}
CHUNK_SIZE = 1024 * 1024


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
        try:
            with os.scandir(path) as it:
                for entry in it:
                    if entry.is_file(follow_symlinks=False):
                        total_size += entry.stat().st_size
                    elif entry.is_dir(follow_symlinks=False):
                        total_size += get_size(Path(entry.path))
        except (PermissionError, OSError):
            pass
        return total_size
    return 0


def format_size(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}" if unit != "B" else f"{size_bytes:.0f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def has_compressed_suffix(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(ext) for ext in SUPPORTED_EXTS)


def output_name_for_file(path: Path, mode: str) -> Path:
    ext_map = {"xz": ".xz", "gz": ".gz", "bz2": ".bz2", "brotli": ".br", "zstd": ".zst", "7z": ".7z"}
    if mode not in ext_map:
        raise ValueError(f"Unsupported mode: {mode}")
    return path.with_name(path.name + ext_map[mode])


def output_name_for_dir(dir_path: Path, mode: str) -> Path:
    ext_map = {
        "xz": ".tar.xz",
        "gz": ".tar.gz",
        "bz2": ".tar.bz2",
        "brotli": ".tar.br",
        "zstd": ".tar.zst",
        "7z": ".tar.7z",
    }
    if mode not in ext_map:
        raise ValueError(f"Unsupported mode: {mode}")
    return dir_path.parent / f"{dir_path.name}{ext_map[mode]}"


def atomic_write(src: Path, dst: Path, write_func, *args, **kwargs) -> Path:
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, dir=dst.parent, prefix=f"{dst.stem}.") as tmp:
            temp_path = Path(tmp.name)
            write_func(src, temp_path, *args, **kwargs)

        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temp_path, dst)
        return dst
    except Exception as e:
        logger.error(f"Atomic write failed for {dst}: {e}")
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise


def tar_directory(src_dir: Path, tar_path: Path) -> None:
    try:
        with tarfile.open(tar_path, "w", dereference=False) as tf:
            tf.add(src_dir, arcname=src_dir.name, recursive=True, filter="data")
    except Exception as e:
        logger.error(f"Failed to create tar for {src_dir}: {e}")
        raise


def compress_file_gz(src: Path, dst: Path) -> None:
    with src.open("rb") as fin:
        with gzip.open(dst, "wb", compresslevel=COMPRESSION_LEVELS["gz"]) as fout:
            shutil.copyfileobj(fin, fout, length=CHUNK_SIZE)


def compress_file_bz2(src: Path, dst: Path) -> None:
    with src.open("rb") as fin:
        with bz2.open(dst, "wb", compresslevel=COMPRESSION_LEVELS["bz2"]) as fout:
            shutil.copyfileobj(fin, fout, length=CHUNK_SIZE)


def compress_file_brotli(src: Path, dst: Path) -> None:
    if brotli is None:
        raise RuntimeError("brotli library not installed")
    data = src.read_bytes()
    compressed = brotli.compress(data, quality=COMPRESSION_LEVELS["brotli"])
    dst.write_bytes(compressed)


def compress_file_7z(src: Path, dst: Path) -> None:
    if py7zr is None:
        raise RuntimeError("py7zr not installed")
    with py7zr.SevenZipFile(dst, "w", filters=[{"id": py7zr.FILTER_LZMA2, "preset": COMPRESSION_LEVELS["7z"]}]) as zf:
        zf.write(src, arcname=src.name)


def compress_file_xz(src: Path, dst: Path) -> None:
    with src.open("rb") as fin:
        with lzma.open(dst, "wb", preset=COMPRESSION_LEVELS["xz"] | lzma.PRESET_EXTREME) as fout:
            shutil.copyfileobj(fin, fout, length=CHUNK_SIZE)


def compress_file_zstd(src: Path, dst: Path) -> None:
    if zstd is None:
        raise RuntimeError("zstandard not installed")
    cctx = zstd.ZstdCompressor(level=COMPRESSION_LEVELS["zstd"])
    with src.open("rb") as fin:
        with dst.open("wb") as fout:
            cctx.copy_stream(fin, fout)


def compress_one(path_str: str, mode: str, is_dir: bool) -> Result:
    src = Path(path_str)
    tar_path = None
    original_size = get_size(src)
    result = Result(ok=False, src=str(src), original_size=original_size)

    try:
        compress_funcs = {
            "xz": compress_file_xz,
            "gz": compress_file_gz,
            "bz2": compress_file_bz2,
            "brotli": compress_file_brotli,
            "zstd": compress_file_zstd,
            "7z": compress_file_7z,
        }

        if mode not in compress_funcs:
            raise ValueError(f"Unsupported compression mode: {mode}")

        if is_dir:
            tar_path = src.parent / f"{src.name}.tar"
            tar_directory(src, tar_path)
            dst = output_name_for_dir(src, mode)

            atomic_write(tar_path, dst, compress_funcs[mode])

            tar_path.unlink(missing_ok=True)
            shutil.rmtree(src)
        else:
            dst = output_name_for_file(src, mode)
            atomic_write(src, dst, compress_funcs[mode])
            src.unlink()

        result.dst = str(dst)
        result.new_size = get_size(dst)
        result.ok = True
        return result

    except Exception as e:
        logger.error(f"Failed to compress {src}: {e}")
        result.error = str(e)
        if tar_path and tar_path.exists():
            tar_path.unlink(missing_ok=True)
        return result


def decompress_one(path_str: str) -> Result:
    src = Path(path_str)
    temp_file_to_remove = None
    original_size = get_size(src)
    result = Result(ok=False, src=str(src), original_size=original_size)

    try:
        name = src.name.lower()
        dst_dir = src.parent

        handlers = {
            ".tar.xz": lambda: handle_tar_xz(src, dst_dir),
            ".tar": lambda: handle_tar(src, dst_dir),
            ".tar.gz": lambda: handle_tar_gz(src, dst_dir),
            ".tar.bz2": lambda: handle_tar_bz2(src, dst_dir),
            ".tar.br": lambda: handle_tar_br(src, dst_dir),
            ".tar.7z": lambda: handle_tar_7z(src, dst_dir),
            ".xz": lambda: handle_single_file(src, dst_dir, lzma_open),
            ".gz": lambda: handle_single_file(src, dst_dir, gzip_open),
            ".bz2": lambda: handle_single_file(src, dst_dir, bz2_open),
            ".br": lambda: handle_brotli(src, dst_dir),
            ".zst": lambda: handle_zstd(src, dst_dir),
            ".tar.zst": lambda: handle_tar_zst(src, dst_dir),
            ".7z": lambda: handle_7z(src, dst_dir),
        }

        for ext, handler in handlers.items():
            if name.endswith(ext):
                extracted_path = handler()
                if extracted_path:
                    result.dst = str(extracted_path)
                    result.new_size = get_size(extracted_path)
                result.ok = True
                src.unlink()
                return result

        raise ValueError(f"Unsupported archive type: {src}")

    except Exception as e:
        logger.error(f"Failed to decompress {src}: {e}")
        result.error = str(e)
        if temp_file_to_remove and temp_file_to_remove.exists():
            temp_file_to_remove.unlink()
        return result


def lzma_open(file, mode) -> LZMAFile | TextIOWrapper:
    return lzma.open(file, mode)


def gzip_open(file, mode) -> GzipFile | TextIOWrapper:
    return gzip.open(file, mode)


def bz2_open(file, mode) -> BZ2File | TextIOWrapper:
    return bz2.open(file, mode)


def handle_single_file(src: Path, dst_dir: Path, open_func):
    extracted_path = src.with_suffix("")
    with open_func(src, "rb") as fin:
        with extracted_path.open("wb") as fout:
            shutil.copyfileobj(fin, fout, length=CHUNK_SIZE)
    return extracted_path


def handle_tar(src: Path, dst_dir: Path):
    extracted_path = dst_dir / src.stem
    with tarfile.open(src, "r:") as tf:
        tf.extractall(path=dst_dir, filter="data")
    return extracted_path


def handle_tar_gz(src: Path, dst_dir: Path):
    extracted_path = dst_dir / src.stem[:-4]
    with tempfile.NamedTemporaryFile(delete=False, dir=dst_dir, suffix=".tar") as tmp_tar:
        temp_path = Path(tmp_tar.name)
        with gzip.open(src, "rb") as fin:
            shutil.copyfileobj(fin, tmp_tar, length=CHUNK_SIZE)
    with tarfile.open(temp_path, "r:") as tf:
        tf.extractall(path=dst_dir, filter="data")
    temp_path.unlink()
    return extracted_path


def handle_tar_bz2(src: Path, dst_dir: Path):
    extracted_path = dst_dir / src.stem[:-5]
    with tempfile.NamedTemporaryFile(delete=False, dir=dst_dir, suffix=".tar") as tmp_tar:
        temp_path = Path(tmp_tar.name)
        with bz2.open(src, "rb") as fin:
            shutil.copyfileobj(fin, tmp_tar, length=CHUNK_SIZE)
    with tarfile.open(temp_path, "r:") as tf:
        tf.extractall(path=dst_dir, filter="data")
    temp_path.unlink()
    return extracted_path


def handle_tar_xz(src: Path, dst_dir: Path):
    extracted_path = dst_dir / src.stem[:-4]
    with tempfile.NamedTemporaryFile(delete=False, dir=dst_dir, suffix=".tar") as tmp_tar:
        temp_path = Path(tmp_tar.name)
        with lzma.open(src, "rb") as fin:
            shutil.copyfileobj(fin, tmp_tar, length=CHUNK_SIZE)
    with tarfile.open(temp_path, "r:") as tf:
        tf.extractall(path=dst_dir, filter="data")
    temp_path.unlink()
    return extracted_path


def handle_tar_br(src: Path, dst_dir: Path):
    if brotli is None:
        raise RuntimeError("brotli not installed")
    extracted_path = dst_dir / src.stem[:-4]
    data = brotli.decompress(src.read_bytes())
    with tempfile.NamedTemporaryFile(delete=False, dir=dst_dir, suffix=".tar") as tmp_tar:
        temp_path = Path(tmp_tar.name)
        tmp_tar.write(data)
    with tarfile.open(temp_path, "r:") as tf:
        tf.extractall(path=dst_dir, filter="data")
    temp_path.unlink()
    return extracted_path


def handle_tar_7z(src: Path, dst_dir: Path):
    if py7zr is None:
        raise RuntimeError("py7zr not installed")
    extracted_path = dst_dir / src.stem[:-4]
    with py7zr.SevenZipFile(src, "r") as zf:
        zf.extractall(path=dst_dir)
    return extracted_path


def handle_tar_zst(src: Path, dst_dir: Path):
    if zstd is None:
        raise RuntimeError("zstandard not installed")
    extracted_path = dst_dir / src.stem[:-4]
    dctx = zstd.ZstdDecompressor()
    with src.open("rb") as fin:
        with dctx.stream_reader(fin) as reader:
            with tarfile.open(fileobj=reader, mode="r|*") as tf:
                tf.extractall(path=dst_dir, filter="data")
    return extracted_path


def handle_brotli(src: Path, dst_dir: Path):
    if brotli is None:
        raise RuntimeError("brotli not installed")
    extracted_path = src.with_suffix("")
    out_bytes = brotli.decompress(src.read_bytes())
    extracted_path.write_bytes(out_bytes)
    return extracted_path


def handle_zstd(src: Path, dst_dir: Path):
    if zstd is None:
        raise RuntimeError("zstandard not installed")
    extracted_path = src.with_suffix("")
    dctx = zstd.ZstdDecompressor()
    with src.open("rb") as fin:
        with extracted_path.open("wb") as fout:
            dctx.copy_stream(fin, fout)
    return extracted_path


def handle_7z(src: Path, dst_dir: Path):
    if py7zr is None:
        raise RuntimeError("py7zr not installed")
    extracted_name = src.stem
    extracted_path = dst_dir / extracted_name
    with py7zr.SevenZipFile(src, "r") as zf:
        zf.extractall(path=dst_dir)
    return extracted_path


def get_safe_workers() -> int:
    if psutil is None:
        return 2

    try:
        total_mem = psutil.virtual_memory().total
        mem_headroom_gb = 2
        mem_per_worker_gb = 2
        max_workers = max(1, int((total_mem / 1024**3 - mem_headroom_gb) / mem_per_worker_gb))
        return min(max_workers, 4)
    except:
        return 2


def mpf3(func, path_str: str):
    if not items:
        return []

    max_workers = get_safe_workers()
    logger.info(f"Using {max_workers} parallel workers")

    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(func, item): item for item in items}
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                item = futures[future]
                logger.error(f"Worker failed for {item}: {e}")
                results.append(Result(ok=False, src=item, error=str(e)))
    return results


def collect_items(base: Path) -> List[Tuple[Path, bool]]:
    items = []
    try:
        for p in base.iterdir():
            if p.name == ".git":
                continue
            if p.is_file() and not has_compressed_suffix(p):
                items.append((p, False))
            elif p.is_dir():
                items.append((p, True))
    except PermissionError:
        logger.warning(f"Permission denied accessing {base}")
    return items


def main() -> None:
    global COMPRESS_MODE

    parser = argparse.ArgumentParser(description="Compress/decompress current directory recursively.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-c", "--compress", action="store_true", help="Compress")
    group.add_argument("-d", "--decompress", action="store_true", help="Decompress")

    method_group = parser.add_mutually_exclusive_group()
    method_group.add_argument("-7", "--7z", dest="use_7z", action="store_true", help="Use 7z")
    method_group.add_argument("-z", "--zstd", action="store_true", help="Use Zstandard (default)")
    method_group.add_argument("-x", "--xz", action="store_true", help="Use XZ")
    method_group.add_argument("-g", "--gz", action="store_true", help="Use Gzip")
    method_group.add_argument("-b", "--brotli", action="store_true", help="Use Brotli")
    method_group.add_argument("--bz2", action="store_true", help="Use Bzip2")

    args = parser.parse_args()

    if not args.compress and not args.decompress:
        args.compress = True

    if args.compress and not (args.use_7z or args.zstd or args.xz or args.gz or args.brotli or args.bz2):
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
                    f"✓ Decompressed: {res.src} -> {res.dst or 'extracted'} | "
                    f"Size: {format_size(res.original_size)} -> {format_size(res.new_size)}"
                )
                overall_original_size += res.original_size
                overall_new_size += res.new_size
            else:
                error_count += 1
                print(f"✗ Failed to decompress: {res.src} - Error: {res.error}")

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

        required_libs = {"brotli": brotli, "zstd": zstd, "7z": py7zr}
        if mode in required_libs and required_libs[mode] is None:
            print(f"Error: {mode} compression requires additional libraries. Please install the required package.")
            return

        base = Path.cwd()
        items_to_process = collect_items(base)

        if not items_to_process:
            print("No files or directories to compress.")
            return

        print(f"Found {len(items_to_process)} items to compress using '{mode}' mode. Starting compression...")
        COMPRESS_MODE = mode

        for path, is_dir in items_to_process:
            res = compress_one(str(path), COMPRESS_MODE, is_dir)
            processed_count += 1
            if res.ok:
                print(
                    f"✓ Compressed: {res.src} -> {res.dst} | "
                    f"Size: {format_size(res.original_size)} -> {format_size(res.new_size)}"
                )
                overall_original_size += res.original_size
                overall_new_size += res.new_size
            else:
                error_count += 1
                print(f"✗ Failed to compress: {res.src} - Error: {res.error}")

    if processed_count == 0:
        print("No items were processed.")
        return

    print(f"\n{'=' * 50}")
    print(f"Processing complete: {processed_count} items, {error_count} errors")

    if overall_original_size > 0:
        reduction = overall_original_size - overall_new_size
        percent_reduction = (reduction / overall_original_size * 100) if overall_original_size > 0 else 0
        print(f"Total original size: {format_size(overall_original_size)}")
        print(f"Total new size:      {format_size(overall_new_size)}")
        print(f"Total reduction:     {format_size(abs(reduction))} ({percent_reduction:.2f}%)")

        if percent_reduction > 0:
            print(f"Space saved:         {format_size(reduction)}")
    else:
        print("Could not determine overall size changes.")


if __name__ == "__main__":
    main()
