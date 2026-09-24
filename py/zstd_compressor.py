import argparse
import io
import tarfile
from multiprocessing import Pool
from pathlib import Path
from typing import BinaryIO
import zstandard as zstd
from loguru import logger

ZSTD_LEVEL = 19
CHUNK_SIZE = 1024 * 64
WORKER_COUNT = 8


def compress_stream(input_stream, output_path):
    try:
        cctx = zstd.ZstdCompressor(level=ZSTD_LEVEL)
        with open(output_path, "wb") as f_out:
            compressor = cctx.stream_writer(f_out)
            while True:
                chunk = input_stream.read(CHUNK_SIZE)
                if not chunk:
                    break
                compressor.write(chunk)
            compressor.close()
        print(f"Compressed: {output_path.name}")
        return True
    except Exception as e:
        logger.error(f"Error compressing to {output_path.name}: {e}")
        return False


def decompress_stream(input_path, output_path):
    try:
        dctx = zstd.ZstdDecompressor()
        with open(input_path, "rb") as f_in, open(output_path, "wb") as f_out:
            decompressor = dctx.stream_reader(f_in)
            while True:
                chunk = decompressor.read(CHUNK_SIZE)
                if not chunk:
                    break
                f_out.write(chunk)
        print(f"Decompressed: {output_path.name}")
        return True
    except Exception as e:
        logger.error(f"Error decompressing {input_path.name}: {e}")
        return False


def process_directory(dir_path):
    output_zst = dir_path.with_name(f"{dir_path.name}.tar.zst")
    tar_buffer = io.BytesIO()
    try:
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            tar.add(dir_path, arcname=dir_path.name)
        tar_buffer.seek(0)
        if compress_stream(tar_buffer, output_zst):
            import shutil

            shutil.rmtree(dir_path)
            print(f"Removed original directory: {dir_path.name}")
    except Exception as e:
        logger.error(f"Failed to archive directory {dir_path.name}: {e}")


def process_file(path):
    output_zst = path.with_name(f"{path.name}.zst")
    try:
        with open(path, "rb") as f_in:
            if compress_stream(f_in, output_zst):
                path.unlink()
                print(f"Removed original file: {path.name}")
    except Exception as e:
        logger.error(f"Failed to compress file {path.name}: {e}")


def decompress_file(zst_path):
    if zst_path.name.endswith(".tar.zst"):
        output_dir = zst_path.with_name(zst_path.name[:-8])
        tar_buffer = io.BytesIO()
        try:
            if decompress_stream(zst_path, tar_buffer):
                tar_buffer.seek(0)
                with tarfile.open(fileobj=tar_buffer, mode="r") as tar:
                    tar.extractall(path=output_dir.parent)
                zst_path.unlink()
                print(f"Removed archive: {zst_path.name}")
        except Exception as e:
            logger.error(f"Failed to decompress tar archive {zst_path.name}: {e}")
    elif zst_path.suffix == ".zst":
        output_file = zst_path.with_suffix("")
        if decompress_stream(zst_path, output_file):
            zst_path.unlink()
            print(f"Removed archive: {zst_path.name}")
    else:
        logger.warning(f"Skipping non-zst file: {zst_path.name}")


def process_item(item, mode):
    item_path = Path(item)
    if mode == "compress":
        if item_path.is_dir():
            process_directory(item_path)
        elif item_path.is_file():
            process_file(item_path)
    else:
        if item_path.is_file():
            decompress_file(item_path)


def main():
    parser = argparse.ArgumentParser(description="Compress/Decompress with Zstandard (zstd)")
    parser.add_argument("-c", "--compress", action="store_true", help="Compress mode (default)")
    parser.add_argument("-d", "--decompress", action="store_true", help="Decompress mode")
    args = parser.parse_args()
    mode = "decompress" if args.decompress else "compress"
    current_dir = Path(".")

    logger.remove()
    logger.add(lambda msg: print(msg, end=""), level="INFO")
    if mode == "compress":
        subdirs = [d for d in current_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        files = [
            f for f in current_dir.iterdir() if f.is_file() and f.suffix != ".zst" and f.name != Path(__file__).name
        ]
        if not subdirs and not files:
            logger.warning("No files or subdirectories found to compress.")
            return 0
        print(f"Found {len(subdirs)} subdirs and {len(files)} files to compress.")
        print(f"Starting parallel Zstandard compression (Level: {ZSTD_LEVEL})...")
        items = subdirs + files
        with Pool(processes=WORKER_COUNT) as pool:
            pool.starmap(process_item, [(item, mode) for item in items])
    else:
        archives = [f for f in current_dir.iterdir() if f.is_file() and f.suffix == ".zst"]
        if not archives:
            logger.warning("No .zst or .tar.zst files found to decompress.")
            return 0
        print(f"Found {len(archives)} archives to decompress.")
        print("Starting parallel decompression...")
        with Pool(processes=WORKER_COUNT) as pool:
            pool.starmap(process_item, [(archive, mode) for archive in archives])
    print("All operations completed successfully!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
