import argparse
import io
import shutil
import tarfile
from multiprocessing import Pool
from pathlib import Path
import brotli
from loguru import logger

BROTLI_QUALITY = 11
CHUNK_SIZE = 1024 * 64
POOL_SIZE = 8
TAR_BR_SUFFIX = ".tar.br"
BR_SUFFIX = ".br"


def decompress_stream(input_path, output_path):
    try:
        with open(input_path, "rb") as f_in:
            decompressor = brotli.Decompressor()
            with open(output_path, "wb") as f_out:
                while True:
                    chunk = f_in.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    f_out.write(decompressor.process(chunk))
        logger.success(f"Decompressed: {output_path.name}")
        return True
    except Exception as e:
        logger.error(f"Error decompressing {input_path.name}: {e}")
        return False


def compress_stream(input_stream, output_path):
    compressor = brotli.Compressor(quality=BROTLI_QUALITY)
    try:
        with open(output_path, "wb") as f_out:
            while True:
                chunk = input_stream.read(CHUNK_SIZE)
                if not chunk:
                    break
                f_out.write(compressor.process(chunk))
            f_out.write(compressor.finish())
        logger.success(f"Compressed: {output_path.name}")
        return True
    except Exception as e:
        logger.error(f"Error compressing to {output_path.name}: {e}")
        return False


def process_directory(dir_path):
    output_br = dir_path.with_name(f"{dir_path.name}{TAR_BR_SUFFIX}")
    tar_buffer = io.BytesIO()
    try:
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            tar.add(dir_path, arcname=dir_path.name)
        tar_buffer.seek(0)
        if compress_stream(tar_buffer, output_br):
            shutil.rmtree(dir_path)
            print(f"Removed original directory: {dir_path.name}")
    except Exception as e:
        logger.error(f"Failed to archive directory {dir_path.name}: {e}")


def process_file(path):
    output_br = path.with_name(f"{path.name}{BR_SUFFIX}")
    try:
        with open(path, "rb") as f_in:
            if compress_stream(f_in, output_br):
                path.unlink()
                print(f"Removed original file: {path.name}")
    except Exception as e:
        logger.error(f"Failed to compress file {path.name}: {e}")


def decompress_file(br_path):
    if br_path.name.endswith(TAR_BR_SUFFIX):
        output_dir = br_path.with_name(br_path.name[: -len(TAR_BR_SUFFIX)])
        tar_buffer = io.BytesIO()
        try:
            tmp_tar = Path(str(br_path) + ".tmp")
            if decompress_stream(br_path, tmp_tar):
                with (
                    open(tmp_tar, "rb") as tf,
                    tarfile.open(fileobj=tf, mode="r") as tar,
                ):
                    tar.extractall(path=output_dir.parent)
                tmp_tar.unlink()
                br_path.unlink()
                print(f"Removed archive: {br_path.name}")
        except Exception as e:
            logger.error(f"Failed to decompress tar archive {br_path.name}: {e}")
    elif br_path.suffix == BR_SUFFIX:
        output_file = br_path.with_suffix("")
        if decompress_stream(br_path, output_file):
            br_path.unlink()
            print(f"Removed archive: {br_path.name}")
    else:
        logger.warning(f"Skipping non-br file: {br_path.name}")


def _collect_compression_targets(current_dir, script_name):
    subdirs = [d for d in current_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
    files = [f for f in current_dir.iterdir() if f.is_file() and f.suffix != BR_SUFFIX and f.name != script_name]
    return subdirs, files


def main():
    parser = argparse.ArgumentParser(description="Compress/Decompress with Brotli")
    parser.add_argument("-c", "--compress", action="store_true", help="Compress mode (default)")
    parser.add_argument("-d", "--decompress", action="store_true", help="Decompress mode")
    args = parser.parse_args()
    mode = "decompress" if args.decompress else "compress"
    current_dir = Path(".")
    if mode == "compress":
        subdirs, files = _collect_compression_targets(current_dir, Path(__file__).name)
        if not subdirs and not files:
            logger.warning("No files or subdirectories found to compress.")
            return 0
        print(f"Found {len(subdirs)} subdirs and {len(files)} files to compress.")
        print(f"Starting parallel compression (Quality: {BROTLI_QUALITY})...")
        with Pool(processes=POOL_SIZE) as pool:
            for d in subdirs:
                pool.apply_async(process_directory, args=(d,))
            for f in files:
                pool.apply_async(process_file, args=(f,))
            pool.close()
            pool.join()
    else:
        archives = [f for f in current_dir.rglob("*") if f.is_file() and f.suffix == BR_SUFFIX]
        if not archives:
            logger.warning("No .br or .tar.br files found to decompress.")
            return 0
        print(f"Found {len(archives)} archives to decompress.")
        print("Starting parallel decompression...")
        with Pool(processes=POOL_SIZE) as pool:
            for archive in archives:
                pool.apply_async(decompress_file, args=(archive,))
            pool.close()
            pool.join()
    logger.success("All operations completed successfully!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
