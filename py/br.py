import contextlib
import sys
import tempfile
import time
from collections import deque
from multiprocessing import Pool
from pathlib import Path

from brotlicffi import compress
from dh import format_size, get_files, get_size
from termcolor import cprint

MAX_QUEUE = 16


def atomic_write(data: bytes, final_path: Path) -> bool:
    temp_dir = final_path.parent
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=temp_dir,
            prefix=".tmp_",
            suffix=final_path.suffix,
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(data)
            temp_file.flush()
        temp_path.rename(final_path)
        return True
    except Exception:
        if temp_path and temp_path.exists():
            with contextlib.suppress(BaseException):
                temp_path.unlink()
        return False


def safe_delete(file_path: Path, max_retries: int = 3, delay: float = 0.5) -> bool:
    for attempt in range(max_retries):
        try:
            if file_path.exists():
                time.sleep(delay)
                file_path.unlink()
                return True
            return True
        except PermissionError:
            if attempt < max_retries - 1:
                time.sleep(delay * (attempt + 1))
                continue
            return False
        except FileNotFoundError:
            return True
        except Exception:
            return False
    return False


def process_file(file_path: Path, delete_delay: float = 0.5) -> bool:
    compressed_path = file_path.with_suffix(file_path.suffix + ".br")
    if compressed_path.exists():
        return False
    try:
        original_size = file_path.stat().st_size
        with file_path.open("rb") as f_in:
            data = f_in.read()
        compressed_data: bytes
        try:
            compressed_data = compress(data, quality=11)
        except MemoryError:
            compressed_data = compress(data, quality=9)
        if not atomic_write(compressed_data, compressed_path):
            return False
        if not compressed_path.exists():
            return False
        compressed_size = compressed_path.stat().st_size
        if compressed_size == 0:
            compressed_path.unlink()
            return False
        if safe_delete(file_path, delay=delete_delay):
            reduction = (1 - compressed_size / original_size) * 100
            cprint(f"{file_path.name} compressed", "green", end=" | ")
            cprint(f"{reduction}", "cyan")
            return True
        else:
            return True
    except PermissionError:
        return False
    except Exception:
        if compressed_path.exists():
            compressed_path.unlink()
        return False


def should_compress(file_path: Path) -> bool:
    if file_path.suffix == ".br":
        return False
    return file_path.stat().st_size != 0


def main() -> None:
    root_dir = Path.cwd()
    before = get_size(root_dir)
    args = sys.argv[1:]
    files = (
        [Path(arg) for arg in args] if args else [p for p in get_files(root_dir, recursive=True) if should_compress(p)]
    )
    if len(files) == 1:
        process_file(files[0])
        return
    results = []
    with Pool(8) as pool:
        pending = deque()
        for f in files:
            pending.append(pool.apply_async(process_file, (f,)))
            if len(pending) > MAX_QUEUE:
                results.append(pending.popleft().get())
        while pending:
            results.append(pending.popleft().get())
    diff_size = before - get_size(root_dir)
    cprint(f"space change: {format_size(diff_size)}")


if __name__ == "__main__":
    sys.exit(main())
