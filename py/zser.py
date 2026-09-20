
import asyncio
import shutil
import sys
from pathlib import Path
import zstandard as zstd
from dh import cprint, fsz, gsz

_executor = asyncio.Semaphore(4)


def fsz(size: float) -> str:
    for unit in ["B", "KiB", "MiB", "GiB", "TiB"]:
        if abs(size) < 1024.0:
            return f"{size:3.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PiB"


async def compress_folder_async(folder_path: Path, output_base_name: str, format="tar") -> bool:
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, lambda: shutil.make_archive(output_base_name, format, str(folder_path)))
        return True
    except Exception as e:
        print(f"Failed to compress folder {folder_path} → {output_base_name}: {e}")
        return False


def compress_file(path: Path) -> bool:
    dst = path.with_suffix(path.suffix + ".zst")
    if dst.exists():
        return False
    before = path.stat().st_size
    try:
        cctx = zstd.ZstdCompressor(level=21)
        with path.open("rb") as fin, dst.open("wb") as fout:
            cctx.copy_stream(fin, fout)
        after = dst.stat().st_size
        if not after:
            print(f"Compressed file empty: {dst}")
            return False
        path.unlink()
        reduction = (before - after) / before * 100
        print(f"{path.name}|{fsz(before)} → {fsz(after)} {reduction:.2f}%")
        return True
    except Exception as e:
        print(f"Compression failed for {path}: {e}")
        return False


def get_files(directory: Path) -> list[Path]:
    return [p for p in directory.glob("*") if p.is_file() and should_compress(p)]


def get_dirs(directory: Path) -> list[Path]:
    return [p for p in directory.glob("*") if not p.is_symlink() and p.is_dir()]


def should_compress(path: Path) -> bool | int:
    path = Path(path)
    try:
        if path.is_symlink():
            return False
        if not path.is_file():
            return False
        compressed_extensions = (".xz", ".br", ".7z", ".zip", ".gz", ".bz2", ".zst", ".whl")
        if path.suffix in compressed_extensions:
            return False
        return path.stat().st_size
    except (OSError, PermissionError):
        return False


async def main_async() -> None:
    sys.argv[1:]
    cwd = Path.cwd()
    before = gsz(cwd)
    dirs = get_dirs(cwd)
    if dirs:
        for dir_path in sorted(dirs):
            if await compress_folder_async(dir_path, str(dir_path.parent / dir_path.name), format="tar"):
                print(f"compressed {dir_path.relative_to(cwd)}")
                shutil.rmtree(dir_path)
    files = get_files(cwd)
    if not files:
        print("No files to compress")
        return
    total_original = 0
    total_compressed = 0
    successful = 0
    total_files = len(files)
    for i, path in enumerate(sorted(files), 1):
        print(f"\n[{i}/{total_files}] {path.name}")
        orig_size = path.stat().st_size
        total_original += orig_size
        if compress_file(path):
            successful += 1
        dst = path.with_suffix(path.suffix + ".zst")
        if dst.exists():
            total_compressed += dst.stat().st_size
    if successful > 0:
        savings = total_original - total_compressed
        savings_percent = savings / total_original * 100
        print(f"Space saved: {fsz(savings)} {savings_percent:.1f}%")
    after = gsz(cwd)
    dsz = abs(before - after)
    ratio = dsz / before * 100
    cprint(f"space saved: {fsz(dsz)} | {ratio:.2f}%")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
