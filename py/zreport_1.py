from pathlib import Path
import zstandard as zstd


def get_uncompressed_size(filepath):
    try:
        with open(filepath, "rb") as f:
            dctx = zstd.ZstdDecompressor()
            frame_params = dctx.frame_parameters(f.read(32))
            if frame_params.uncompressed_size:
                return frame_params.uncompressed_size
            else:
                f.seek(0)
                decompressed = dctx.stream_reader(f)
                size = 0
                while True:
                    chunk = decompressed.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                return size
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return None


def format_size(size_bytes):
    if size_bytes is None:
        return "Unknown"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def main():
    dir_path = Path(".")
    zst_files = list(dir_path.glob("*.zst"))
    if not zst_files:
        print("No .zst files found in the current directory.")
        return
    print(f"Found {len(zst_files)} Zstandard file(s) in {dir_path.absolute()}\n")
    print("-" * 80)
    total_compressed = 0
    total_uncompressed = 0
    file_stats = []
    for filepath in sorted(zst_files):
        compressed_size = filepath.stat().st_size
        uncompressed_size = get_uncompressed_size(filepath)
        file_stats.append({"name": filepath.name, "compressed": compressed_size, "uncompressed": uncompressed_size})
        total_compressed += compressed_size
        if uncompressed_size is not None:
            total_uncompressed += uncompressed_size
        ratio = uncompressed_size / compressed_size if uncompressed_size else None
        ratio_str = f"{ratio:.2f}x" if ratio else "Unknown"
        print(f"File: {filepath.name}")
        print(f"  Compressed size:   {format_size(compressed_size)}")
        if uncompressed_size is not None:
            print(f"  Uncompressed size: {format_size(uncompressed_size)}")
            print(f"  Compression ratio: {ratio_str}")
        else:
            print(f"  Uncompressed size: Unknown (not stored in header)")
        print("-" * 40)
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total compressed size:   {format_size(total_compressed)}")
    if total_uncompressed > 0:
        print(f"Total uncompressed size: {format_size(total_uncompressed)}")
        print(f"Total disk space needed:  {format_size(total_uncompressed)}")
        if total_compressed > 0:
            ratio = total_uncompressed / total_compressed
            print(f"Overall compression ratio: {ratio:.2f}x")
        try:
            import shutil

            total, used, free = shutil.disk_usage(".")
            print(f"\nAvailable disk space: {format_size(free)}")
            if total_uncompressed > free:
                print("⚠️  WARNING: Not enough disk space available!")
                print(f"   Need: {format_size(total_uncompressed)}")
                print(f"   Have: {format_size(free)}")
                print(f"   Shortfall: {format_size(total_uncompressed - free)}")
            else:
                print("✓ Enough disk space available.")
        except:
            pass
    else:
        print("Total uncompressed size: Unknown (some files missing size info)")
        print("To get accurate sizes, consider using: zstd -l -v *.zst")
    print("=" * 80)


if __name__ == "__main__":
    main()
