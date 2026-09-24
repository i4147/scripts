import argparse
import lzma
import tarfile
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys


COMPRESSED_EXTENSIONS = {".xz", ".br", ".gz", ".zst", ".7z", ".lz4", ".bz2", ".zip", ".whl"}


class FileCompressor:
    def __init__(self, preset=6):
        self.preset = preset
        self.freed_space = 0
        self.compressed_files = 0
        self.skipped_files = 0
        self.errors = []

    def compress_file(self, file_path):
        try:
            file_path = Path(file_path)

            if file_path.suffix in COMPRESSED_EXTENSIONS:
                self.skipped_files += 1
                return None

            original_size = file_path.stat().st_size
            xz_path = file_path.with_suffix(file_path.suffix + ".xz")

            if xz_path.exists():
                self.skipped_files += 1
                return None

            with open(file_path, "rb") as f_in:
                with lzma.LZMAFile(xz_path, "wb", preset=self.preset) as f_out:
                    shutil.copyfileobj(f_in, f_out)

            compressed_size = xz_path.stat().st_size
            freed = original_size - compressed_size
            self.freed_space += freed
            self.compressed_files += 1

            file_path.unlink()

            return {"file": file_path.name, "original": original_size, "compressed": compressed_size, "freed": freed}
        except Exception as e:
            self.errors.append(f"Error compressing {file_path}: {e}")
            return None

    def compress_directory_tar(self, dir_path):
        try:
            dir_path = Path(dir_path)
            tar_name = f"{dir_path.name}.tar"
            tar_path = dir_path.parent / tar_name
            tar_xz_path = tar_path.with_suffix(".tar.xz")

            with tarfile.open(tar_path, "w") as tar:
                tar.add(dir_path, arcname=dir_path.name)

            tar_size = tar_path.stat().st_size

            with open(tar_path, "rb") as f_in:
                with lzma.LZMAFile(tar_xz_path, "wb", preset=self.preset) as f_out:
                    shutil.copyfileobj(f_in, f_out)

            tar_xz_size = tar_xz_path.stat().st_size
            freed = tar_size - tar_xz_size
            self.freed_space += freed

            tar_path.unlink()
            shutil.rmtree(dir_path)

            print(f"✓ Compressed directory: {dir_path.name}")
            print(f"  Tar size: {self._format_size(tar_size)} → {self._format_size(tar_xz_size)}")
            print(f"  Space freed: {self._format_size(freed)}")

            self.compressed_files += 1
            return tar_xz_size
        except Exception as e:
            self.errors.append(f"Error compressing directory {dir_path}: {e}")
            return None

    def decompress_file(self, file_path):
        try:
            file_path = Path(file_path)

            if file_path.suffix != ".xz":
                self.skipped_files += 1
                return None

            output_path = file_path.with_suffix("")

            if output_path.exists():
                self.skipped_files += 1
                return None

            xz_size = file_path.stat().st_size

            with lzma.LZMAFile(file_path, "rb") as f_in:
                with open(output_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)

            original_size = output_path.stat().st_size
            self.compressed_files += 1

            file_path.unlink()

            return {"file": output_path.name, "original": original_size, "compressed": xz_size}
        except Exception as e:
            self.errors.append(f"Error decompressing {file_path}: {e}")
            return None

    def process_directory(self, dir_path, recursive=True, max_workers=4):
        dir_path = Path(dir_path)
        files_to_process = []

        if recursive:
            files_to_process = list(dir_path.rglob("*"))
        else:
            files_to_process = list(dir_path.glob("*"))

        files_to_process = [f for f in files_to_process if f.is_file()]

        print(f"Found {len(files_to_process)} files to process...\n")

        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.compress_file, f): f for f in files_to_process}

            for i, future in enumerate(as_completed(futures), 1):
                result = future.result()
                if result:
                    results.append(result)
                    print(
                        f"[{i}/{len(files_to_process)}] ✓ {result['file']} ({self._format_size(result['freed'])} freed)"
                    )

        return results

    def print_summary(self):
        print("\n" + "=" * 60)
        print("COMPRESSION SUMMARY")
        print("=" * 60)
        print(f"Files compressed: {self.compressed_files}")
        print(f"Files skipped: {self.skipped_files}")
        print(f"Total space freed: {self._format_size(self.freed_space)}")

        if self.errors:
            print(f"\nErrors ({len(self.errors)}):")
            for error in self.errors:
                print(f"  ✗ {error}")

        print("=" * 60 + "\n")

    @staticmethod
    def _format_size(bytes_size):
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if bytes_size < 1024:
                return f"{bytes_size:.2f} {unit}"
            bytes_size /= 1024
        return f"{bytes_size:.2f} PB"


def main():
    parser = argparse.ArgumentParser(description="Compress files using LZMA (xz) with parallel processing")
    parser.add_argument("path", nargs="?", default=".", help="Path to compress (default: current directory)")
    parser.add_argument("-c", "--compress", action="store_true", help="Compress files")
    parser.add_argument("-d", "--decompress", action="store_true", help="Decompress xz files")
    parser.add_argument("-t", "--tar", action="store_true", help="Create tar.xz archives of subdirectories")
    parser.add_argument(
        "-p",
        "--preset",
        type=int,
        default=6,
        choices=range(10),
        help="LZMA compression preset (0=fast, 9=best, default=6)",
    )
    parser.add_argument("-w", "--workers", type=int, default=4, help="Number of parallel workers (default=4)")
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        default=True,
        help="Process subdirectories recursively (default: True)",
    )

    args = parser.parse_args()

    if not args.compress and not args.decompress and not args.tar:
        parser.print_help()
        sys.exit(1)

    if args.compress and args.decompress:
        print("Error: Cannot use -c and -d together")
        sys.exit(1)

    path = Path(args.path)
    if not path.exists():
        print(f"Error: Path does not exist: {path}")
        sys.exit(1)

    compressor = FileCompressor(preset=args.preset)

    if args.tar:
        print(f"Creating tar.xz archives from subdirectories in {path}...\n")
        for subdir in sorted(path.iterdir()):
            if subdir.is_dir() and not subdir.name.startswith("."):
                compressor.compress_directory_tar(subdir)

    elif args.compress:
        print(f"Compressing files in {path}...\n")
        compressor.process_directory(path, recursive=args.recursive, max_workers=args.workers)

    elif args.decompress:
        print(f"Decompressing xz files in {path}...\n")
        xz_files = list(path.rglob("*.xz")) if args.recursive else list(path.glob("*.xz"))

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(compressor.decompress_file, f): f for f in xz_files}

            for i, future in enumerate(as_completed(futures), 1):
                result = future.result()
                if result:
                    print(f"[{i}/{len(xz_files)}] ✓ {result['file']}")

    compressor.print_summary()


if __name__ == "__main__":
    main()
