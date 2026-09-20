import contextlib
import shutil
import sys
import tempfile
from pathlib import Path

import lzma_mt
from loguru import logger


def compress_folder(folder_path: Path, output_base_name: str, format="tar") -> bool:
    try:
        shutil.make_archive(output_base_name, format, str(folder_path))
        return True
    except Exception as e:
        return False


def atomic_write(data: bytes, final_path: Path) -> bool:
    temp_dir = final_path.parent
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=temp_dir,
            prefix=".tmp_",
            suffix=".xz",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(data)
            temp_file.flush()
        temp_path.rename(final_path)
        logger.debug(f"Atomically written to: {final_path}")
        return True
    except Exception as e:
        logger.error(f"Atomic write failed for {final_path}: {e}")
        if temp_path and temp_path.exists():
            with contextlib.suppress(BaseException):
                temp_path.unlink()
        return False


def safe_delete(path: Path, max_retries: int = 3) -> bool:
    for attempt in range(max_retries):
        try:
            if path.exists():
                if path.is_dir():
                    shutil.rmtree(str(path))
                else:
                    path.unlink()
                return True
        except PermissionError:
            if attempt < max_retries - 1:
                continue
            logger.error(f"Cannot delete {path} after {max_retries} attempts due to PermissionError")
            return False
        except FileNotFoundError:
            logger.debug(f"File not found during deletion attempt: {path}")
            return True
        except Exception as e:
            logger.error(f"Error deleting {path}: {e}")
            return False
    return False


def compress_file(path: Path) -> bool:
    compressed_path = path.with_suffix(path.suffix + ".xz")
    if compressed_path.exists():
        return False
    try:
        original_size = path.stat().st_size
        with path.open("rb") as f_in:
            data = f_in.read()
        compressed_data: bytes
        compressed_data = lzma_mt.compress(data, threads=4, preset=9)
        if not atomic_write(compressed_data, compressed_path):
            return False
        if not compressed_path.exists() or not compressed_path.stat().st_size:
            return False
        if safe_delete(path):
            compressed_size = compressed_path.stat().st_size
            reduction = ((original_size - compressed_size) / original_size) * 100
            logger.info(f"{path.name}|{fsz(original_size)} → {fsz(compressed_size)} ({reduction:.2f}% reduction)")
            return True
    except Exception:
        return False


def gsz(cwd: Path = Path.cwd()) -> tuple[int, int]:
    total_size = 0
    file_count = 0
    for path in cwd.rglob("*"):
        if path.is_file() and not path.is_symlink():
            if any(part.startswith(".") for part in path.parts):
                continue
            try:
                size = path.stat().st_size
                total_size += size
                file_count += 1
            except (OSError, PermissionError, FileNotFoundError):
                continue
    return total_size, file_count


def get_files(directory: Path) -> list[Path]:
    return [p for p in directory.glob("*") if p.is_file() and not p.is_symlink() and should_compress(p)]


def get_dirs(cwd: Path) -> list[Path]:
    return [p for p in cwd.glob("*") if not p.is_symlink() and p.is_dir()]


def should_compress(path: Path) -> bool | int:
    path = Path(path)
    try:
        if path.is_symlink():
            return False
        if not path.is_file():
            return False
        compressed_extensions = (
            ".xz",
            ".br",
            ".7z",
        )
        if path.suffix in compressed_extensions:
            return False
        return path.stat().st_size
    except (OSError, PermissionError):
        return False


def main() -> None:
    sys.argv[1:]
    cwd = Path.cwd()
    dirs_to_compress = get_dirs(cwd)
    if dirs_to_compress:
        for dir_path in dirs_to_compress:
            logger.info(f"compressing {dir_path.relative_to(cwd)}")
            output_tar_file = str(dir_path.parent / dir_path.name)
            if compress_folder(str(dir_path), output_tar_file, format="tar"):
                logger.info(f"compressed {dir_path.relative_to(cwd)}")
                safe_delete(dir_path)
    files_to_compress = get_files(cwd)
    if not files_to_compress:
        logger.info("No files to compress")
        return
    total_original = 0
    total_compressed = 0
    successful = 0
    for i, path in enumerate(files_to_compress, 1):
        logger.info(f"\n[{i}/{len(files_to_compress)}] Processing...")
        orig_size = path.stat().st_size
        total_original += orig_size
        if compress_file(path):
            successful += 1
            compressed_path = path.with_suffix(path.suffix + ".xz")
            if compressed_path.exists():
                total_compressed += compressed_path.stat().st_size
    if successful > 0:
        savings = total_original - total_compressed
        savings_percent = (savings / total_original) * 100
        logger.info(f"Space saved: {fsz(savings)} ({savings_percent:.1f}%)")


if __name__ == "__main__":
    sys.exit(main())
