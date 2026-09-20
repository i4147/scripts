
import argparse
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import brotlicffi


def make_compress_input(data_bytes):
    return data_bytes


def compress_file(input_path: str, output_path: str, quality: int = 6):
    try:
        
        with open(input_path, "rb") as f:
            data = f.read()

        
        compressor = brotlicffi.Compressor(quality=quality)
        compressed = compressor.process(data)
        compressed += compressor.finish()

        
        with open(output_path, "wb") as f:
            f.write(compressed)

        
        original_size = len(data)
        compressed_size = len(compressed)
        ratio = (compressed_size / original_size) * 100 if original_size > 0 else 0

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


def decompress_file(input_path: str, output_path: str):
    try:
        
        with open(input_path, "rb") as f:
            compressed_data = f.read()

        
        decompressor = brotlicffi.Decompressor()
        decompressed = decompressor.process(compressed_data)

        if not decompressor.is_finished():
            
            decompressed += decompressor.finish()

        
        with open(output_path, "wb") as f:
            f.write(decompressed)

        return {
            "success": True,
            "input": input_path,
            "output": output_path,
            "original_size": len(compressed_data),
            "decompressed_size": len(decompressed),
        }
    except Exception as e:
        return {"success": False, "input": input_path, "error": str(e)}


def compress_directory(input_dir: str, output_dir=None, quality: int = 6, max_workers: int = 4) -> bool:
    input_path = Path(input_dir)

    if not input_path.exists():
        print(f"Error: Directory '{input_dir}' does not exist")
        return False

    if output_dir is None:
        output_dir = input_path.parent / f"{input_path.name}_compressed"
    else:
        output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    
    files_to_compress = []
    for file_path in input_path.rglob("*"):
        if file_path.is_file():
            
            rel_path = file_path.relative_to(input_path)
            output_path = output_dir / f"{rel_path}.br"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            files_to_compress.append((file_path, output_path))

    if not files_to_compress:
        print(f"No files found in '{input_dir}'")
        return False

    print(f"Compressing {len(files_to_compress)} files using {max_workers} threads...")
    start_time = time.time()

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        
        future_to_file = {
            executor.submit(compress_file, str(in_path), str(out_path), quality): in_path
            for in_path, out_path in files_to_compress
        }

        
        for future in as_completed(future_to_file):
            result = future.result()
            results.append(result)
            if result["success"]:
                print(f"  ✓ Compressed: {result['input']} → {result['output']} ({result['ratio']:.1f}% of original)")
            else:
                print(f"  ✗ Failed: {result['input']} - {result['error']}")

    elapsed_time = time.time() - start_time

    
    successful = sum(1 for r in results if r["success"])
    total_original = sum(r.get("original_size", 0) for r in results if r["success"])
    total_compressed = sum(r.get("compressed_size", 0) for r in results if r["success"])
    total_ratio = (total_compressed / total_original) * 100 if total_original > 0 else 0

    print(f"\n{'=' * 60}")
    print(f"Compression Complete!")
    print(f"  Files processed: {successful}/{len(results)} successful")
    print(f"  Total size: {total_original:,} bytes → {total_compressed:,} bytes")
    print(f"  Overall ratio: {total_ratio:.1f}%")
    print(f"  Time taken: {elapsed_time:.2f} seconds")
    print(f"  Output directory: {output_dir}")
    print(f"{'=' * 60}")

    return successful > 0


def decompress_directory(input_dir: str, output_dir=None, max_workers: int = 4) -> bool:
    input_path = Path(input_dir)

    if not input_path.exists():
        print(f"Error: Directory '{input_dir}' does not exist")
        return False

    if output_dir is None:
        
        base_name = input_path.name
        if base_name.endswith("_compressed"):
            output_dir = input_path.parent / base_name.replace("_compressed", "_decompressed")
        else:
            output_dir = input_path.parent / f"{base_name}_decompressed"
    else:
        output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    
    files_to_decompress = []
    for file_path in input_path.rglob("*.br"):
        
        rel_path = file_path.relative_to(input_path)
        output_path = output_dir / rel_path.with_suffix("")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        files_to_decompress.append((file_path, output_path))

    if not files_to_decompress:
        print(f"No .br files found in '{input_dir}'")
        return False

    print(f"Decompressing {len(files_to_decompress)} files using {max_workers} threads...")
    start_time = time.time()

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        
        future_to_file = {
            executor.submit(decompress_file, str(in_path), str(out_path)): in_path
            for in_path, out_path in files_to_decompress
        }

        
        for future in as_completed(future_to_file):
            result = future.result()
            results.append(result)
            if result["success"]:
                print(f"  ✓ Decompressed: {result['input']} → {result['output']}")
            else:
                print(f"  ✗ Failed: {result['input']} - {result['error']}")

    elapsed_time = time.time() - start_time

    
    successful = sum(1 for r in results if r["success"])
    total_original = sum(r.get("original_size", 0) for r in results if r["success"])
    total_decompressed = sum(r.get("decompressed_size", 0) for r in results if r["success"])

    print(f"\n{'=' * 60}")
    print(f"Decompression Complete!")
    print(f"  Files processed: {successful}/{len(results)} successful")
    print(f"  Total size: {total_original:,} bytes → {total_decompressed:,} bytes")
    print(f"  Time taken: {elapsed_time:.2f} seconds")
    print(f"  Output directory: {output_dir}")
    print(f"{'=' * 60}")

    return successful > 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compress or decompress files/directories using Brotli",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Compress a single file
  python brotli_tool.py -c document.txt
  
  # Compress a directory with high compression
  python brotli_tool.py -c myfolder -q 11 --threads 8
  
  # Decompress a file
  python brotli_tool.py -d document.txt.br
  
  # Decompress a directory
  python brotli_tool.py -d compressed_folder
        """,
    )

    parser.add_argument("-c", "--compress", metavar="PATH", help="Compress the specified file or directory")

    parser.add_argument("-d", "--decompress", metavar="PATH", help="Decompress the specified file or directory")

    parser.add_argument(
        "-q",
        "--quality",
        type=int,
        default=6,
        choices=range(0, 12),
        help="Compression quality (0-11, default: 6). Higher = better compression but slower",
    )

    parser.add_argument(
        "-t", "--threads", type=int, default=4, help="Number of threads for parallel processing (default: 4)"
    )

    parser.add_argument("-o", "--output", help="Output directory path (for directory operations)")

    args = parser.parse_args()

    
    if not args.compress and not args.decompress:
        parser.error("Either -c/--compress or -d/--decompress is required")

    if args.compress and args.decompress:
        parser.error("Cannot use both -c/--compress and -d/--decompress")

    
    if args.compress:
        path = Path(args.compress)

        if not path.exists():
            print(f"Error: Path '{args.compress}' does not exist")
            sys.exit(1)

        if path.is_file():
            
            output_file = path.with_suffix(f"{path.suffix}.br")
            if args.output:
                output_file = Path(args.output) / path.name
                output_file = output_file.with_suffix(f"{output_file.suffix}.br")

            print(f"Compressing file: {path}")
            result = compress_file(str(path), str(output_file), args.quality)

            if result["success"]:
                print(f"✓ Compression successful!")
                print(f"  Original: {result['original_size']:,} bytes")
                print(f"  Compressed: {result['compressed_size']:,} bytes")
                print(f"  Ratio: {result['ratio']:.1f}%")
                print(f"  Output: {result['output']}")
            else:
                print(f"✗ Compression failed: {result['error']}")
                sys.exit(1)

        elif path.is_dir():
            
            success = compress_directory(str(path), args.output, args.quality, args.threads)
            if not success:
                sys.exit(1)

    
    elif args.decompress:
        path = Path(args.decompress)

        if not path.exists():
            print(f"Error: Path '{args.decompress}' does not exist")
            sys.exit(1)

        if path.is_file():
            
            if not path.suffix == ".br":
                print(f"Warning: File '{path}' doesn't have .br extension")
                proceed = input("Continue anyway? (y/n): ").lower()
                if proceed != "y":
                    sys.exit(0)

            
            output_file = path.with_suffix("")
            if args.output:
                output_file = Path(args.output) / path.name.replace(".br", "")

            print(f"Decompressing file: {path}")
            result = decompress_file(str(path), str(output_file))

            if result["success"]:
                print(f"✓ Decompression successful!")
                print(f"  Original: {result['original_size']:,} bytes")
                print(f"  Decompressed: {result['decompressed_size']:,} bytes")
                print(f"  Output: {result['output']}")
            else:
                print(f"✗ Decompression failed: {result['error']}")
                sys.exit(1)

        elif path.is_dir():
            
            success = decompress_directory(str(path), args.output, args.threads)
            if not success:
                sys.exit(1)


if __name__ == "__main__":
    main()
