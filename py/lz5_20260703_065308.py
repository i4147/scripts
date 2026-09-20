
import argparse
import shutil
import tarfile
import lz4.frame
from pathlib import Path
from multiprocessing import Pool, cpu_count
import io


def compress_folder(folder_path):
    folder = Path(folder_path)
    if not folder.is_dir():
        return f"Skipped {folder}: Not a directory"

    
    tar_lz4_path = folder.with_suffix(".tar.lz4")
    if tar_lz4_path.exists():
        return f"Skipped {folder}: Already compressed"

    try:
        
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            tar.add(folder, arcname=folder.name)

        
        tar_data = tar_buffer.getvalue()
        compressed = lz4.frame.compress(tar_data, compression_level=3)

        
        with open(tar_lz4_path, "wb") as f:
            f.write(compressed)

        
        shutil.rmtree(folder)

        return f"Compressed: {folder} -> {tar_lz4_path}"

    except Exception as e:
        return f"Error compressing {folder}: {e}"


def decompress_file(file_path):
    file = Path(file_path)
    if not file.suffix == ".lz4" or not file.stem.endswith(".tar"):
        return f"Skipped {file}: Not a tar.lz4 file"

    
    folder_name = file.stem[:-4]  
    folder_path = file.parent / folder_name

    
    if folder_path.exists():
        return f"Skipped {file}: Already decompressed"

    try:
        
        with open(file, "rb") as f:
            compressed_data = f.read()

        decompressed = lz4.frame.decompress(compressed_data)

        
        tar_buffer = io.BytesIO(decompressed)
        with tarfile.open(fileobj=tar_buffer, mode="r") as tar:
            tar.extractall(path=file.parent)

        
        file.unlink()

        return f"Decompressed: {file} -> {folder_path}"

    except Exception as e:
        return f"Error decompressing {file}: {e}"


def main():
    parser = argparse.ArgumentParser(
        description="Compress/decompress folders with LZ4",
        epilog="Default action: compress subfolders in current directory",
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("-c", "--compress", action="store_true", help="Compress subfolders")
    group.add_argument("-d", "--decompress", action="store_true", help="Decompress .tar.lz4 files")

    args = parser.parse_args()

    current_dir = Path.cwd()

    
    if not args.compress and not args.decompress:
        args.compress = True

    
    if args.compress:
        items = [d for d in current_dir.iterdir() if d.is_dir()]
        process_func = compress_folder
        action = "Compressing"
    else:  
        items = [f for f in current_dir.iterdir() if f.is_file() and f.suffix == ".lz4" and f.stem.endswith(".tar")]
        process_func = decompress_file
        action = "Decompressing"

    if not items:
        print(f"No {'folders' if args.compress else '.tar.lz4 files'} found")
        return

    print(f"{action} {len(items)} items using {cpu_count()} processes...")

    
    with Pool(processes=cpu_count()) as pool:
        results = pool.map(process_func, items)

    
    for result in results:
        print(result)

    print(f"\n{action} complete!")


if __name__ == "__main__":
    main()
