from __future__ import annotations

import argparse
import io
import tarfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import brotli

BROTLI_QUALITY = 11
CHUNK_SIZE = 1024 * 64


def decompress_stream(input_path: Path, output_path: Path) -> bool:
    try:
        with open(input_path, "rb") as f_in:
            decompressor = brotli.Decompressor()
            with open(output_path, "wb") as f_out:
                while True:
                    chunk = f_in.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    f_out.write(decompressor.process(chunk))
        print(f"✅ Decompressed: {output_path.name}")
        return True
    except Exception as e:
        print(f"❌ Error decompressing {input_path.name}: {e}")
        return False


def compress_stream(input_stream, output_file_path: Path) -> bool:
    compressor = brotli.Compressor(quality=BROTLI_QUALITY)
    try:
        with open(output_file_path, "wb") as f_out:
            while True:
                chunk = input_stream.read(CHUNK_SIZE)
                if not chunk:
                    break
                f_out.write(compressor.process(chunk))
            f_out.write(compressor.finish())
        print(f"✅ Compressed: {output_file_path.name}")
        return True
    except Exception as e:
        print(f"❌ Error compressing to {output_file_path.name}: {e}")
        return False


def process_directory(dir_path: Path):
    output_br = dir_path.with_name(f"{dir_path.name}.tar.br")
    tar_buffer = io.BytesIO()
    try:
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            tar.add(dir_path, arcname=dir_path.name)
        tar_buffer.seek(0)
        if compress_stream(tar_buffer, output_br):
            import shutil

            shutil.rmtree(dir_path)
            print(f"🗑️  Removed original directory: {dir_path.name}")
    except Exception as e:
        print(f"❌ Failed to archive directory {dir_path.name}: {e}")


def process_file(file_path: Path):
    output_br = file_path.with_name(f"{file_path.name}.br")
    try:
        with open(file_path, "rb") as f_in:
            if compress_stream(f_in, output_br):
                file_path.unlink()
                print(f"🗑️  Removed original file: {file_path.name}")
    except Exception as e:
        print(f"❌ Failed to compress file {file_path.name}: {e}")


def decompress_file(br_path: Path):
    if br_path.name.endswith(".tar.br"):
        output_dir = br_path.with_name(br_path.name[:-7])
        tar_buffer = io.BytesIO()
        try:
            if decompress_stream(br_path, tar_buffer):
                tar_buffer.seek(0)
                with tarfile.open(fileobj=tar_buffer, mode="r") as tar:
                    tar.extractall(path=output_dir.parent)
                br_path.unlink()
                print(f"🗑️  Removed archive: {br_path.name}")
        except Exception as e:
            print(f"❌ Failed to decompress tar archive {br_path.name}: {e}")
    elif br_path.suffix == ".br":
        output_file = br_path.with_suffix("")
        if decompress_stream(br_path, output_file):
            br_path.unlink()
            print(f"🗑️  Removed archive: {br_path.name}")
    else:
        print(f"⚠️  Skipping non-br file: {br_path.name}")


def main():
    parser = argparse.ArgumentParser(description="Compress/Decompress with Brotli")
    parser.add_argument("-c", "--compress", action="store_true", help="Compress mode (default)")
    parser.add_argument("-d", "--decompress", action="store_true", help="Decompress mode")
    args = parser.parse_args()
    mode = "decompress" if args.decompress else "compress"
    current_dir = Path(".")
    if mode == "compress":
        subdirs = [d for d in current_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        files = [
            f for f in current_dir.iterdir() if f.is_file() and f.suffix != ".br" and f.name != Path(__file__).name
        ]
        if not subdirs and not files:
            print("No files or subdirectories found to compress.")
            return
        print(f"🚀 Found {len(subdirs)} subdirs and {len(files)} files to compress.")
        print(f"⚡ Starting parallel compression (Quality: {BROTLI_QUALITY})...")
        with ThreadPoolExecutor() as executor:
            for d in subdirs:
                executor.submit(process_directory, d)
            for f in files:
                executor.submit(process_file, f)
    else:
        archives = [f for f in current_dir.iterdir() if f.is_file() and f.suffix == ".br"]
        if not archives:
            print("No .br or .tar.br files found to decompress.")
            return
        print(f"🚀 Found {len(archives)} archives to decompress.")
        print("⚡ Starting parallel decompression...")
        with ThreadPoolExecutor() as executor:
            for archive in archives:
                executor.submit(decompress_file, archive)
    print("🎉 All operations completed successfully!")


if __name__ == "__main__":
    raise SystemExit(main())
