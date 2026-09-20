from __future__ import annotations

import multiprocessing as mp
import shutil
import sys
import tarfile
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import zstandard as zstd


def compress_chunk(chunk_data):
    compressor = zstd.ZstdCompressor(level=3, threads=4)
    return compressor.compress(chunk_data)


def get_file_list(directory, exclude_patterns=None):
    if exclude_patterns is None:
        exclude_patterns = {".git", ".tar.zst", ".zst"}
    files = []
    for item in directory.rglob("*"):
        if any(pattern in item.parts for pattern in exclude_patterns):
            continue
        if item.name.endswith(".tar.zst") or item.name.endswith(".zst"):
            continue
        files.append(item)
    return files


def create_archive_optimized():
    current_dir = Path.cwd()
    dir_name = current_dir.name
    parent_dir = current_dir.parent
    if str(current_dir) == "/" or str(current_dir) == str(Path.home()):
        print("Error: Cannot archive root or home directory")
        sys.exit(1)
    archive_path = parent_dir / f"{dir_name}.tar.zst"
    if archive_path.exists():
        response = input(f"Overwrite {archive_path}? (y/n): ").strip().lower()
        if response not in ["y", "yes"]:
            print("Aborted")
            sys.exit(0)
    try:
        files = get_file_list(current_dir)
        if not files:
            print("No files to archive")
            sys.exit(1)
        with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp_tar:
            tmp_tar_path = tmp_tar.name
            with tarfile.open(tmp_tar_path, "w") as tar:
                with ThreadPoolExecutor(max_workers=min(4, mp.cpu_count())) as executor:

                    def add_file(file_path):
                        tar.add(file_path, arcname=file_path.relative_to(parent_dir))

                    list(executor.map(add_file, files))
            compressor = zstd.ZstdCompressor(level=3, threads=mp.cpu_count())
            CHUNK_SIZE = 1024 * 1024 * 8
            with open(tmp_tar_path, "rb") as f_in, open(archive_path, "wb") as f_out:
                while True:
                    chunk = f_in.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    compressed_chunk = compressor.compress(chunk)
                    f_out.write(compressed_chunk)
                f_out.write(compressor.flush())
            Path(tmp_tar_path).unlink(missing_ok=True)
        if archive_path.exists() and archive_path.stat().st_size > 0:
            test_dir = parent_dir / f"{dir_name}_test"
            try:
                with tarfile.open(archive_path, "r:zstd") as tar:
                    tar.extractall(test_dir)
                shutil.rmtree(current_dir)
                print(f"✓ Archive created: {archive_path}")
                print(f"✓ Original directory removed: {current_dir}")
            except Exception:
                if test_dir.exists():
                    shutil.rmtree(test_dir)
                raise
        else:
            print("Error: Archive creation failed")
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        if "tmp_tar_path" in locals():
            Path(tmp_tar_path).unlink(missing_ok=True)
        if archive_path.exists():
            archive_path.unlink()
        sys.exit(1)


def create_archive_streaming_fixed():
    current_dir = Path.cwd()
    dir_name = current_dir.name
    parent_dir = current_dir.parent
    if str(current_dir) == "/" or str(current_dir) == str(Path.home()):
        print("Error: Cannot archive root or home directory")
        sys.exit(1)
    archive_path = parent_dir / f"{dir_name}.tar.zst"
    if archive_path.exists():
        response = input(f"Overwrite {archive_path}? (y/n): ").strip().lower()
        if response not in ["y", "yes"]:
            print("Aborted")
            sys.exit(0)
    try:
        compressor = zstd.ZstdCompressor(level=3, threads=mp.cpu_count())
        with (
            open(archive_path, "wb") as f_out,
            compressor.stream_writer(f_out) as zstd_writer,
            tarfile.open(fileobj=zstd_writer, mode="w:") as tar,
        ):
            files = get_file_list(current_dir)
            if not files:
                print("No files to archive")
                sys.exit(1)
            for file_path in files:
                tar.add(file_path, arcname=file_path.relative_to(parent_dir))
        if archive_path.exists() and archive_path.stat().st_size > 0:
            test_dir = parent_dir / f"{dir_name}_test"
            try:
                with tarfile.open(archive_path, "r:zstd") as tar:
                    tar.extractall(test_dir)
                shutil.rmtree(test_dir)
                shutil.rmtree(current_dir)
                print(f"✓ Archive created: {archive_path}")
                print(f"✓ Original directory removed: {current_dir}")
            except Exception:
                if test_dir.exists():
                    shutil.rmtree(test_dir)
                raise
        else:
            print("Error: Archive creation failed")
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        if archive_path.exists():
            archive_path.unlink()
        sys.exit(1)


if __name__ == "__main__":
    create_archive_optimized()
