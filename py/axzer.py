import asyncio
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import lzma_mt
from loguru import logger

_executor = ThreadPoolExecutor(max_workers=4)


def _compress_with_lzma(data: bytes) -> bytes:
    return lzma_mt.compress(data, threads=4, preset=9)


def fsz(size: int) -> str:
    for unit in ["B", "KiB", "MiB", "GiB", "TiB"]:
        if abs(size) < 1024.0:
            return f"{size:3.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PiB"


async def compress_folder_async(folder_path: Path, output_base_name: str, format: str = "tar") -> bool:
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(
            _executor, lambda: shutil.make_archive(str(output_base_name), format, str(folder_path))
        )
        return True
    except Exception as e:
        logger.error(f"Failed to compress folder {folder_path} → {output_base_name}: {e}")
        return False


async def atomic_write_async(data: bytes, final_path: Path) -> bool:
    temp_dir = final_path.parent
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = None
    loop = asyncio.get_running_loop()
    try:

        def _create_temp() -> Path:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=temp_dir,
                prefix=".tmp_",
                suffix=".xz",
                delete=False,
            ) as f:
                f.write(data)
                f.flush()
                return Path(f.name)

        temp_path = await loop.run_in_executor(_executor, _create_temp)
        await loop.run_in_executor(_executor, lambda: temp_path.rename(final_path))
        logger.debug(f"Atomically written to: {final_path}")
        return True
    except Exception as e:
        logger.error(f"Atomic write failed for {final_path}: {e}")
        if temp_path and temp_path.exists():
            try:
                await asyncio.get_running_loop().run_in_executor(_executor, temp_path.unlink)
            except Exception:
                pass


async def safe_delete_async(path: Path, max_retries: int = 3) -> bool:
    loop = asyncio.get_running_loop()
    for attempt in range(max_retries):
        try:
            if not path.exists():
                return True
                if path.is_dir():
                    shutil.rmtree(str(path))
                else:
                    path.unlink()
            await loop.run_in_executor(_executor, _delete)
            return True
        except PermissionError:
            if attempt < max_retries - 1:
                await asyncio.sleep(0.1 * (attempt + 1))
            logger.error(f"Cannot delete {path} after {max_retries} attempts due to PermissionError")
            return False
        except FileNotFoundError:
            logger.debug(f"File not found during deletion attempt: {path}")
            return True
        except Exception as e:
            logger.error(f"Error deleting {path}: {e}")
            return False
    return False


async def compress_file_async(path: Path) -> bool:
    compressed_path = path.with_suffix(path.suffix + ".xz")
    if compressed_path.exists():
        return False
    try:
        loop = asyncio.get_running_loop()

        def _read() -> bytes:
            with path.open("rb") as f:
                return f.read()

        data = await loop.run_in_executor(_executor, _read)
        original_size = path.stat().st_size
        compressed_data = await loop.run_in_executor(_executor, _compress_with_lzma, data)
        if not await atomic_write_async(compressed_data, compressed_path):
            return False
        compressed_size = compressed_path.stat().st_size
        if not compressed_size:
            logger.error(f"Compressed file empty: {compressed_path}")
            return False
        if not await safe_delete_async(path):
            logger.warning(f"Failed to delete original after compression: {path}")
            return False
    except:
        pass
