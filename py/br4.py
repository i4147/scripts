from __future__ import annotations

import argparse
import shutil
import sys
import tarfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import brotlicffi


def compress_file(input_path: Path, output_path: Path, quality: int = 6) -> dict:
    try:
        data = input_path.read_bytes()
        compressor = brotlicffi.Compressor(quality=quality)
        compressed = compressor.process(data)
        compressed += compressor.finish()
        output_path.write_bytes(compressed)
        original_size = len(data)
        compressed_size = len(compressed)
        ratio = compressed_size / original_size * 100 if original_size > 0 else 0
        return {
            "success": True,
            "input": input_path,
            "output": output_path,
            "original_size": original_size,
            "compressed_size": compressed_size,
            "ratio": ratio,
        }
    except Exception as e:
        return {"success": False, "input": input_path, "error": str(e)}


def decompress_file(input_path: Path, output_path: Path) -> dict:
    try:
        compressed_data = input_path.read_bytes()
        decompressor = brotlicffi.Decompressor()
        decompressed = decompressor.process(compressed_data)
        if not decompressor.is_finished():
            decompressed += decompressor.finish()
        output_path.write_bytes(decompressed)
        return {
            "success": True,
            "input": input_path,
            "output": output_path,
            "original_size": len(compressed_data),
            "decompressed_size": len(decompressed),
        }
    except Exception as e:
        return {"success": False, "input": input_path, "error": str(e)}


def compress_directory_to_tar(input_dir: Path, quality: int = 6) -> Path | None:
    tar_path = input_dir.with_suffix(".tar")
    compressed_path = input_dir.with_suffix(".tar.br")
    try:
        print(f"  Creating tar archive: {tar_path.name}")
        with tarfile.open(tar_path, "w") as tar:
            tar.add(input_dir, arcname=input_dir.name)
        print(f"  Compressing tar archive: {compressed_path.name}")
        result = compress_file(tar_path, compressed_path, quality)
        if result["success"]:
            shutil.rmtree(input_dir)
            tar_path.unlink()
            return compressed_path
        else:
            if tar_path.exists():
                tar_path.unlink()
            return None
    except Exception as e:
        print(f"  Error compressing directory: {e}")
        if tar_path.exists():
            tar_path.unlink()
        return None


def decompress_tar_br(input_path: Path, output_dir: Path | None = None) -> Path | None:
    if input_path.suffixes != [".tar", ".br"]:
        print(f"  Error: {input_path} is not a .tar.br file")
        return None
    if output_dir is None:
        output_path = input_path.parent / input_path.stem.replace(".tar", "")
    else:
        output_path = output_dir / input_path.stem.replace(".tar", "")
    tar_path = input_path.with_suffix("")
    try:
        print(f"  Decompressing: {input_path.name}")
        result = decompress_file(input_path, tar_path)
        if not result["success"]:
            return None
        print(f"  Extracting: {tar_path.name}")
        with tarfile.open(tar_path, "r") as tar:
            extract_dir = output_path.parent
            tar.extractall(path=extract_dir)
        tar_path.unlink()
        input_path.unlink()
        return output_path
    except Exception as e:
        print(f"  Error decompressing {input_path}: {e}")
        if tar_path.exists():
            tar_path.unlink()
        return None


def compress_path(input_path: Path, quality: int = 6, max_workers: int = 4) -> bool:
    if not input_path.exists():
        print(f"Error: Path '{input_path}' does not exist")
        return False
    if input_path.is_file():
        compressed_path = input_path.with_suffix(f"{input_path.suffix}.br")
        if input_path.suffix == ".tar":
            compressed_path = input_path.with_suffix(".tar.br")
        print(f"Compressing file: {input_path}")
        result = compress_file(input_path, compressed_path, quality)
        if result["success"]:
            input_path.unlink()
            print("✓ Compression successful!")
            print(f"  Original: {result['original_size']:,} bytes")
            print(f"  Compressed: {result['compressed_size']:,} bytes")
            print(f"  Ratio: {result['ratio']:.1f}%")
            print(f"  Output: {result['output']}")
            return True
        else:
            print(f"✗ Compression failed: {result['error']}")
            return False
    elif input_path.is_dir():
        if input_path.suffix == ".br":
            print("Error: Cannot compress a .br directory")
            return False
        print(f"Compressing directory: {input_path}")
        compressed_path = compress_directory_to_tar(input_path, quality)
        if compressed_path:
            print("✓ Directory compression successful!")
            print(f"  Output: {compressed_path}")
            return True
        else:
            print("✗ Directory compression failed")
            return False


def decompress_path(input_path: Path, max_workers: int = 4) -> bool:
    if not input_path.exists():
        print(f"Error: Path '{input_path}' does not exist")
        return False
    if input_path.is_file():
        if input_path.suffixes == [".tar", ".br"]:
            print(f"Decompressing tar archive: {input_path}")
            output_dir = decompress_tar_br(input_path)
            if output_dir:
                print("✓ Decompression successful!")
                print(f"  Extracted to: {output_dir}")
                return True
            else:
                print("✗ Decompression failed")
                return False
        elif input_path.suffix == ".br":
            output_path = input_path.with_suffix("")
            print(f"Decompressing file: {input_path}")
            result = decompress_file(input_path, output_path)
            if result["success"]:
                input_path.unlink()
                print("✓ Decompression successful!")
                print(f"  Original: {result['original_size']:,} bytes")
                print(f"  Decompressed: {result['decompressed_size']:,} bytes")
                print(f"  Output: {result['output']}")
                return True
            else:
                print(f"✗ Decompression failed: {result['error']}")
                return False
        else:
            print(f"Error: '{input_path}' doesn't have .br extension")
            return False
    elif input_path.is_dir():
        br_files = list(input_path.rglob("*.br"))
        tar_br_files = [f for f in br_files if f.suffixes == [".tar", ".br"]]
        regular_br_files = [f for f in br_files if f.suffix == ".br" and f not in tar_br_files]
        if not br_files:
            print(f"No compressed files found in '{input_path}'")
            return False
        print(f"Found {len(br_files)} compressed files to decompress")
        success_count = 0
        for tar_br_file in tar_br_files:
            print(f"\nProcessing: {tar_br_file.relative_to(input_path)}")
            if decompress_tar_br(tar_br_file):
                success_count += 1
        if regular_br_files:
            print(f"\nDecompressing {len(regular_br_files)} regular files using {max_workers} threads...")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = []
                for br_file in regular_br_files:
                    output_path = br_file.with_suffix("")
                    future = executor.submit(decompress_file, br_file, output_path)
                    futures.append((future, br_file))
                for future, br_file in futures:
                    result = future.result()
                    if result["success"]:
                        result["input"].unlink()
                        print(f"  ✓ Decompressed: {result['output']}")
                        success_count += 1
                    else:
                        print(f"  ✗ Failed: {br_file} - {result['error']}")
        print(f"\n{'=' * 60}")
        print("Decompression Complete!")
        print(f"  Files decompressed: {success_count}/{len(br_files)}")
        print(f"{'=' * 60}")
        return success_count > 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compress or decompress files/directories using Brotli",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Compress current directory (default when no args)
  python brotli_tool.py

  # Compress a single file
  python brotli_tool.py -c document.txt

  # Compress a directory (creates .tar.br)
  python brotli_tool.py -c myfolder -q 11

  # Decompress a file
  python brotli_tool.py -d document.txt.br

  # Decompress a .tar.br file (extracts to directory)
  python brotli_tool.py -d myfolder.tar.br

  # Decompress all files in a directory
  python brotli_tool.py -d compressed_folder -t 8
        """,
    )
    parser.add_argument(
        "-c",
        "--compress",
        metavar="PATH",
        nargs="?",
        const=".",
        help="Compress the specified file or directory (default: current directory if no path given)",
    )
    parser.add_argument(
        "-d",
        "--decompress",
        metavar="PATH",
        nargs="?",
        const=".",
        help="Decompress the specified file or directory (default: current directory if no path given)",
    )
    parser.add_argument(
        "-q",
        "--quality",
        type=int,
        default=6,
        choices=range(12),
        help="Compression quality (0-11, default: 6). Higher = better compression but slower",
    )
    parser.add_argument(
        "-t",
        "--threads",
        type=int,
        default=4,
        help="Number of threads for parallel processing (default: 4)",
    )
    args = parser.parse_args()
    if not args.compress and not args.decompress:
        print("No arguments provided. Compressing current directory...")
        args.compress = "."
    if args.compress:
        path = Path.cwd() if args.compress == "." else Path(args.compress)
        success = compress_path(path, args.quality, args.threads)
        sys.exit(0 if success else 1)
    elif args.decompress:
        path = Path.cwd() if args.decompress == "." else Path(args.decompress)
        success = decompress_path(path, args.threads)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
