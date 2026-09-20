from __future__ import annotations

import argparse
import sys
import tarfile
from contextlib import contextmanager, suppress
from pathlib import Path

from brotlicffi import Compressor, Decompressor

SKIP_DIRS = frozenset({"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"})

CHUNK_SIZE = 524288
LARGE_FILE_THRESHOLD = 2 * 1024 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Brotli compression/decompression tool (brotlicffi backend)",
        epilog="Example: brotli_tool.py -cf *.txt -rm",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-c", "--compress", action="store_true", help="Compress files (default if no op specified)")
    group.add_argument("-d", "--decompress", action="store_true", help="Decompress .br files")
    parser.add_argument(
        "-f",
        "--files",
        nargs="+",
        metavar="FILE",
        help="Files to process (default: recursive current dir)",
    )
    parser.add_argument(
        "-k",
        "--keep",
        action="store_true",
        help="Keep original files (default: remove after success)",
    )
    parser.add_argument(
        "--no-tar",
        action="store_true",
        help="Disable tar-based subdir compression (process files individually)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Show detailed progress")
    return parser.parse_args()


def find_files_to_process(base_dir: Path, recursive: bool = True) -> list[Path]:
    files = []
    for p in base_dir.iterdir():
        if p.is_file() and not p.name.endswith(".br") and not p.name.startswith("."):
            files.append(p)
        elif p.is_dir() and recursive and p.name != "__pycache__":
            files.extend(find_files_to_process(p, recursive))
    return sorted(files)


def compress_file_chunked(src: Path, dst: Path, verbose: bool = False) -> bool:
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(src, "rb") as f_in, open(dst, "wb") as f_out:
            compressor = Compressor()
            while True:
                chunk = f_in.read(CHUNK_SIZE)
                if not chunk:
                    break
                compressed = compressor.process(chunk, quality=11)
                f_out.write(compressed)
            final = compressor.finish()
            f_out.write(final)
        if dst.stat().st_size == 0:
            dst.unlink()
            return False
        return True
    except Exception as e:
        if dst.exists():
            dst.unlink()
        if verbose:
            print(f"❌ Compression failed for {src}: {e}", file=sys.stderr)
        return False


def decompress_file_chunked(src: Path, dst: Path, verbose: bool = False) -> bool:
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(src, "rb") as f_in, open(dst, "wb") as f_out:
            decompressor = Decompressor()
            while True:
                chunk = f_in.read(CHUNK_SIZE)
                if not chunk:
                    break
                decompressed = decompressor.decompress(chunk)
                f_out.write(decompressed)
            final = decompressor.decompress(b"")
            if final:
                f_out.write(final)
        if dst.stat().st_size == 0:
            dst.unlink()
            return False
        return True
    except Exception as e:
        if dst.exists():
            dst.unlink()
        if verbose:
            print(f"❌ Decompression failed for {src}: {e}", file=sys.stderr)
        return False


@contextmanager
def temp_tar_compression(files: list[Path], out_dir: Path, verbose: bool = False):
    tar_path = None
    br_path = None
    try:
        tar_path = out_dir / "temp_compressed.tar"
        with tarfile.open(tar_path, "w") as tar:
            for f in files:
                tar.add(f, arcname=f.name)
        br_path = out_dir / f"{tar_path.name}.br"
        if verbose:
            print(f"📦 Compressing {len(files)} files as tar → {br_path.name}")
        if compress_file_chunked(tar_path, br_path, verbose):
            yield br_path
        else:
            yield None
    finally:
        for p in [tar_path, br_path]:
            if p and p.exists():
                with suppress(Exception):
                    p.unlink()


def process_directory(base_dir: Path, compress: bool, keep: bool, no_tar: bool, verbose: bool = False) -> int:
    success_count = 0
    total_files = 0
    files = find_files_to_process(base_dir)
    if not files:
        if verbose:
            print("ℹ️  No files to process in current directory")
        return 0
    subdirs = [d for d in base_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
    if subdirs and not no_tar:
        for subdir in subdirs:
            subdir_files = find_files_to_process(subdir, recursive=False)
            if subdir_files:
                total_files += len(subdir_files)
                with temp_tar_compression(subdir_files, base_dir, verbose) as br_file:
                    if br_file and br_file.exists():
                        success_count += 1
                        if not keep:
                            for f in subdir_files:
                                if f.exists():
                                    f.unlink()
                            if verbose:
                                print(f"✅ Compressed subdir '{subdir.name}' → {br_file.name}")
                    elif verbose:
                        print(f"⚠️  Skipping subdir '{subdir.name}' (compression failed)")
    for f in files:
        total_files += 1
        if compress:
            src = f
            dst = f.with_suffix(f.suffix + ".br")
            if verbose:
                print(f"📦 Compressing {src.name} → {dst.name}")
            if compress_file_chunked(src, dst, verbose):
                success_count += 1
                if not keep:
                    src.unlink()
            elif verbose:
                print(f"⚠️  Skipping {src.name} (compression failed)")
        else:
            if not f.name.endswith(".br"):
                continue
            src = f
            dst = src.with_suffix("")
            if verbose:
                print(f"📦 Decompressing {src.name} → {dst.name}")
            if decompress_file_chunked(src, dst, verbose):
                success_count += 1
                if not keep:
                    src.unlink()
            elif verbose:
                print(f"⚠️  Skipping {src.name} (decompression failed)")
    return success_count


def main():
    args = parse_args()
    compress = args.compress or not args.decompress
    if args.files:
        files = []
        for path in args.files:
            p = Path(path)
            if p.exists():
                files.append(p)
            else:
                print(f"⚠️  Warning: File '{path}' not found", file=sys.stderr)
        if not files:
            print("❌ No valid files provided", file=sys.stderr)
            sys.exit(1)
        success = 0
        for f in files:
            if compress:
                dst = f.with_suffix(f.suffix + ".br")
                if f.stat().st_size > LARGE_FILE_THRESHOLD:
                    print(f"📦 Compressing large file: {f.name} ({f.stat().st_size / (1024 * 1024):.1f} MB)")
                if compress_file_chunked(f, dst, args.verbose):
                    success += 1
                    if not args.keep:
                        f.unlink()
                else:
                    print(f"⚠️  Compression failed for {f.name}", file=sys.stderr)
            else:
                if not f.name.endswith(".br"):
                    print(f"⚠️  Skipping non-.br file: {f.name}", file=sys.stderr)
                    continue
                dst = f.with_suffix("")
                if decompress_file_chunked(f, dst, args.verbose):
                    success += 1
                    if not args.keep:
                        f.unlink()
                else:
                    print(f"⚠️  Decompression failed for {f.name}", file=sys.stderr)
        if args.verbose:
            print(f"\n✅ Processed {len(files)} files, {success} successful")
        sys.exit(0 if success == len(files) else 1)
    else:
        base_dir = Path()
        success = process_directory(base_dir, compress, args.keep, args.no_tar, args.verbose)
        if args.verbose:
            print("\n✅ Completed directory processing")
        sys.exit(0 if success >= 0 else 1)


if __name__ == "__main__":
    main()
